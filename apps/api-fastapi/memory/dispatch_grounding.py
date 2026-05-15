"""Loop CAP-B Φ.3 — dispatch-time tenant grounding pre-fetch.

The dispatch path needs grounding the chat path doesn't. Chat intake
is the operator's natural-language message, which the Lambda intake-
keyword retrieval can mine for tsquery / path / filename signals.
Dispatch intake is a one-line work-order description ("Klear.ai Intro
5 slides — that talks about Klear.ai ability to support large US
cities") which yields nothing actionable from intake-keyword
retrieval — Mark and Tom end up with no Klear-specific grounding.

This module closes that gap by reading the operator-curated
`client_brand_profiles` row (Loop CAP-A Φ.1) and producing a single
`MemorySource(kind="client_grounding")` carrying the consolidated
brand truth (palette, fonts, voice, ICP, brand terms,
design-input-source preference). The source slots into
SOURCE_PRIORITY position 0 — above canonical_facts — because brand
profile is operator-curated truth and canonical_facts is correctional.

Architectural locks honored (per CAP v0.3.0):
  - D6   — `client_grounding` at SOURCE_PRIORITY slot 0.
  - D11  — uses live `client_brand_profiles` shape from Φ.1; no
           parallel routing enum.
  - D12  — dispatch-time only; no WO-open caching; no propagation.
           Each dispatch re-runs (matches Lambda D-L2 freshness).

Audit:
  Emits exactly one `memory.applied` row with `surface="dispatch_prefetch"`
  per dispatch invocation, regardless of whether a brand profile exists
  for the tenant. The `sources_used` list carries one `client_grounding`
  entry when found, or zero entries when the tenant has no brand row
  (or only an empty-skeleton row — see the `_has_meaningful_grounding`
  gate).

Firewall (Iota / ADR-031):
  - Layer 1: client_id is the WHERE predicate.
  - Layer 2: caller passes a tenant-scoped FastAPI conn (set role
             iwo3_app + app.current_client_id at the connection level).
  - Layer 3: explicit `client_id = $1::uuid` predicate belt.
  - Layer 4: returned MemorySource carries `client_id`; downstream
             validator (assembler-side) confirms ownership before
             injection.
  - Layer 5: no cross-call cache for the brand profile (revision is
             monotonic; future optimization could cache by revision
             but the current cost is one indexed point query).
"""

from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg

from authz.audit_writer import write_audit_row

from .budget import estimate_tokens
from .types import MemorySource


_DISPATCH_PREFETCH_SURFACE = "dispatch_prefetch"
_MEMORY_APPLIED_EVENT = "memory.applied"


def _maybe_load_jsonb(value: Any) -> Any:
    """asyncpg returns jsonb columns as already-decoded Python objects
    by default; some drivers / configurations return strings. Accept
    both shapes."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _format_palette(palette: Any) -> Optional[str]:
    palette = _maybe_load_jsonb(palette) or {}
    if not isinstance(palette, dict) or not palette:
        return None
    parts: list[str] = []
    for key in ("primary", "secondary", "accent"):
        if key in palette:
            parts.append(f"{key}={palette[key]}")
    neutrals = palette.get("neutrals")
    if isinstance(neutrals, dict):
        for nk, nv in neutrals.items():
            parts.append(f"{nk}={nv}")
    return ", ".join(parts) if parts else None


def _format_fonts(fonts: Any) -> Optional[str]:
    fonts = _maybe_load_jsonb(fonts) or {}
    if not isinstance(fonts, dict) or not fonts:
        return None
    parts: list[str] = []
    for key in ("heading", "body"):
        if key in fonts:
            parts.append(f"{key}={fonts[key]}")
    fallbacks = fonts.get("fallbacks")
    if isinstance(fallbacks, list) and fallbacks:
        parts.append("fallbacks=" + ", ".join(str(x) for x in fallbacks))
    return "; ".join(parts) if parts else None


def _format_design_inputs(design: Any) -> Optional[str]:
    design = _maybe_load_jsonb(design) or {}
    if not isinstance(design, dict) or not design:
        return None
    enabled = [k for k in ("stitch", "figma", "twentyfirst") if design.get(k)]
    default = design.get("default_for_html")
    parts: list[str] = []
    if enabled:
        parts.append("enabled=" + ", ".join(enabled))
    if default:
        parts.append(f"default_for_html={default}")
    return "; ".join(parts) if parts else None


def _format_brand_profile_text(row: dict) -> str:
    """Render the brand profile row as a markdown-ish text block. The
    block is inserted under the `## CLIENT BRAND PROFILE` header by
    `render_block` — this function produces just the body."""
    lines: list[str] = []

    palette = _format_palette(row.get("palette_json"))
    if palette:
        lines.append(f"- **Palette:** {palette}")

    fonts = _format_fonts(row.get("fonts_json"))
    if fonts:
        lines.append(f"- **Fonts:** {fonts}")

    voice = (row.get("voice_brief") or "").strip()
    if voice:
        lines.append(f"- **Voice / tone:** {voice}")

    icp = (row.get("icp_summary") or "").strip()
    if icp:
        lines.append(f"- **ICP (ideal customer profile):** {icp}")

    brand_terms = row.get("brand_terms") or []
    if isinstance(brand_terms, (list, tuple)) and brand_terms:
        # Show first 8 to keep tokens predictable.
        head = list(brand_terms)[:8]
        more = len(brand_terms) - len(head)
        suffix = f", … (+{more} more)" if more > 0 else ""
        lines.append(f"- **Brand terms:** {', '.join(head)}{suffix}")

    design = _format_design_inputs(row.get("design_input_sources_json"))
    if design:
        lines.append(f"- **Design input sources:** {design}")

    requires_qa = row.get("requires_brand_qa")
    if requires_qa is not None:
        lines.append(
            f"- **Brand QA required:** {'yes' if requires_qa else 'no'}"
        )

    return "\n".join(lines)


def _has_meaningful_grounding(row: dict) -> bool:
    """Skeleton-row gate. A meaningful brand profile carries at least
    one of: a non-empty palette, fonts, voice_brief, or icp_summary.
    `brand_terms` and `template_handles_json` are operational
    (Aiden Φ.8 detector + Paul Φ.5 template selection) but produce
    no useful prompt content for Mark/Tom — they are not grounding.

    Skeleton rows (e.g. FF before brand assets land) skip grounding
    silently rather than waste 30-50 tokens on a `Brand terms:` line
    that doesn't help the LLM author content."""
    palette = _maybe_load_jsonb(row.get("palette_json")) or {}
    if isinstance(palette, dict) and palette:
        return True
    fonts = _maybe_load_jsonb(row.get("fonts_json")) or {}
    if isinstance(fonts, dict) and fonts:
        return True
    if (row.get("voice_brief") or "").strip():
        return True
    if (row.get("icp_summary") or "").strip():
        return True
    return False


async def prefetch_dispatch_grounding(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[MemorySource]:
    """Pre-fetch tenant brand grounding for a dispatch-time bundle.

    Inputs:
      conn            — tenant-scoped FastAPI connection (firewall
                        Layer 2). Caller is responsible for SET LOCAL
                        ROLE iwo3_app + app.current_client_id.
      client_id       — active tenant.
      actor_user_id   — operator UUID for audit attribution. May be
                        None for fully-async dispatch flows; the audit
                        row will record None and downstream queries
                        will read it from the WO row instead.

    Returns:
      MemorySource(kind="client_grounding") when the tenant has a
      meaningful brand profile (≥ 2 fields populated). None otherwise.

    Side effects:
      Always emits exactly one `memory.applied` audit row with
      `surface="dispatch_prefetch"`. The `sources_used` list reflects
      whether grounding was found (1 entry) or skipped (0 entries).
      This makes the AC-5 assertion ("dispatch shows memory.applied
      with surface=dispatch_prefetch") deterministic regardless of
      brand-profile readiness.
    """
    # Fetch the row. Single indexed point query; no need for the
    # composite-CTE pattern the Iota assembler uses for retrieval.
    # client_id predicate is the firewall belt (RLS hard-walls the
    # rest).
    row = await conn.fetchrow(
        """
        SELECT id::text                  AS id,
               client_id::text           AS client_id,
               palette_json::text        AS palette_json,
               fonts_json::text          AS fonts_json,
               voice_brief,
               icp_summary,
               requires_brand_qa,
               template_handles_json::text AS template_handles_json,
               design_input_sources_json::text AS design_input_sources_json,
               brand_terms,
               revision
        FROM client_brand_profiles
        WHERE client_id = $1::uuid
        """,
        client_id,
    )

    source: Optional[MemorySource] = None
    if row is not None and _has_meaningful_grounding(dict(row)):
        text = _format_brand_profile_text(dict(row))
        if text.strip():
            source = MemorySource(
                kind="client_grounding",
                client_id=row["client_id"],
                record_id=row["id"],
                text=text,
                tokens=estimate_tokens(text),
                owner_user_id=None,  # tenant-shared, not operator-owned
                metadata={
                    "revision": int(row["revision"] or 0),
                    "requires_brand_qa": bool(row["requires_brand_qa"]),
                    "match_kind": "tenant_brand_profile",
                },
            )

    # Emit the dispatch_prefetch audit regardless of source presence.
    # AC-5 asserts the event always fires for branded WO dispatch;
    # zero `sources_used` is a valid (but informative) bundle for
    # tenants that haven't authored a brand profile yet.
    sources_used = (
        [
            {
                "kind": source.kind,
                "record_id": source.record_id,
                "tokens": source.tokens,
                "metadata": source.metadata,
            }
        ]
        if source is not None
        else []
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event=_MEMORY_APPLIED_EVENT,
        target_type="memory_bundle",
        target_id=None,
        metadata={
            "client_id": client_id,
            "user_id": actor_user_id,
            "surface": _DISPATCH_PREFETCH_SURFACE,
            "sources_used": sources_used,
            "tokens_used": source.tokens if source else 0,
            "truncated_kinds": [],
            "cache_hits": [],
            "memory_budget_ms": 0,
            "rejected_count": 0,
        },
    )

    return source
