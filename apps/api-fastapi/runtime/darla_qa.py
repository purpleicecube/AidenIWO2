"""Loop CAP-D Φ.6 — Darla brand QA gate.

Darla scores rendered output (or content envelope + intended template
when pre-render check) against the tenant brand profile and emits a
three-way verdict (`pass | needs_revision | block`).

Verdict semantics:
  - pass            — content honors brand profile across palette /
                      fonts / voice / asset usage. Chain proceeds to
                      `deliver` step (Paul, Φ.5).
  - needs_revision  — partial mismatch with actionable revision notes.
                      Workflow plumbing (chain-runtime side, deferred)
                      returns to the render step with notes; render
                      sub-agent regenerates. Hard cap of 2 revision
                      cycles per WO (O-002 mitigation).
  - block           — egregious violation that operator must adjudicate.
                      Workflow halts publish, opens a new
                      execution_cycle, surfaces operator-actionable
                      transition. Two-cycle cap also applies.

Architectural locks honored (per CAP v0.3.0):
  - P4   — Darla is a GATE, not advisory. Day-one of CAP-D ships gate
           semantics; advisory-only mode never existed.
  - D3   — locked: gate from day one (no two-step migration).
  - D6   — Darla reads `client_brand_profiles` directly; this is the
           authoritative brand truth source.
  - D8   — Darla `block` blocks publish. No silent unbrand fallback.

CAP-D scope:
  This module ships the helper. Wire-in to chain step execution
  (`execute_step_run` recognizing step_key="brand_qa") happens in
  this same loop. Workflow revision-cycle plumbing (returning to
  render step on `needs_revision`) is the chain-runtime piece;
  full revision-cycle activation needs CAP-E Φ.8 to route branded
  WOs to chains in the first place.

Audit:
  Emits exactly one of three events per Darla invocation:
    darla.qa_passed | darla.qa_needs_revision | darla.qa_blocked
  Distinct events (not a single event with metadata) so operators
  can filter audit history by verdict directly.

Firewall:
  Caller passes a tenant-scoped FastAPI conn; Darla reads
  client_brand_profiles via that conn (RLS enforces tenant
  isolation transparently).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import asyncpg

from authz.audit_writer import write_audit_row

from .tier_2_subagents import invoke_tier_2


DarlaVerdict = Literal["pass", "needs_revision", "block"]


@dataclass(frozen=True)
class BrandAttestation:
    """Structured Darla output. Persisted on workflow_step_runs.output
    when the step_key is `brand_qa`. Read by the chain runtime to
    decide whether to proceed to the `deliver` step (Paul, Φ.5),
    return to render with revision notes, or halt publish.
    """

    overall: DarlaVerdict
    palette_pass: bool
    fonts_pass: bool
    voice_pass: bool
    asset_pass: bool
    notes: tuple[str, ...] = field(default_factory=tuple)
    # Free-form metadata Darla can attach (e.g. specific palette
    # mismatches, off-tone phrases, missing logo placements).
    diagnostic: dict[str, Any] = field(default_factory=dict)


_AUDIT_EVENTS_BY_VERDICT: dict[DarlaVerdict, str] = {
    "pass": "darla.qa_passed",
    "needs_revision": "darla.qa_needs_revision",
    "block": "darla.qa_blocked",
}


async def _load_brand_profile_text(
    conn: asyncpg.Connection, *, client_id: str
) -> Optional[str]:
    """Render the tenant brand profile as a text block Darla can
    score against. Reuses the same shape `dispatch_grounding` formats
    so Darla and Mark/Tom see consistent brand truth."""
    row = await conn.fetchrow(
        """
        SELECT palette_json::text   AS palette_json,
               fonts_json::text     AS fonts_json,
               voice_brief,
               icp_summary,
               brand_terms,
               revision
        FROM client_brand_profiles
        WHERE client_id = $1::uuid
        """,
        client_id,
    )
    if row is None:
        return None
    parts: list[str] = []
    palette = row["palette_json"]
    if palette:
        parts.append(f"PALETTE: {palette}")
    fonts = row["fonts_json"]
    if fonts:
        parts.append(f"FONTS: {fonts}")
    if (row["voice_brief"] or "").strip():
        parts.append(f"VOICE: {row['voice_brief']}")
    if (row["icp_summary"] or "").strip():
        parts.append(f"ICP: {row['icp_summary']}")
    if row["brand_terms"]:
        parts.append(f"BRAND TERMS: {', '.join(row['brand_terms'])}")
    if not parts:
        return None
    return "\n".join(parts)


def _parse_attestation(result_or_envelope: Any) -> BrandAttestation:
    """Parse Darla's structured output into a BrandAttestation. Falls
    back to a `block` verdict with a parse-failure note if the LLM
    returned something that doesn't match the contract — failing
    closed is the right posture for a brand QA gate.

    Accepts either a `Tier2InvocationResult` (the public
    `invoke_tier_2` return type) or a bare `Tier2OutputEnvelope`.
    Reads structured fields from `envelope.metadata` jsonb (the
    standard Tier-2 sub-agent metadata channel)."""
    payload: dict[str, Any] = {}
    envelope = getattr(result_or_envelope, "output_envelope", result_or_envelope)
    metadata = getattr(envelope, "metadata", None)
    if isinstance(metadata, dict):
        payload = metadata
    elif isinstance(result_or_envelope, dict):
        payload = result_or_envelope.get("metadata") or result_or_envelope

    overall = payload.get("overall") or payload.get("verdict")
    if overall not in ("pass", "needs_revision", "block"):
        return BrandAttestation(
            overall="block",
            palette_pass=False,
            fonts_pass=False,
            voice_pass=False,
            asset_pass=False,
            notes=("Darla output did not match the structured contract; failing closed.",),
            diagnostic={"raw_payload": str(payload)[:500]},
        )

    notes_raw = payload.get("notes") or []
    if isinstance(notes_raw, str):
        notes_tuple: tuple[str, ...] = (notes_raw,)
    elif isinstance(notes_raw, list):
        notes_tuple = tuple(str(n) for n in notes_raw if n)
    else:
        notes_tuple = ()

    return BrandAttestation(
        overall=overall,  # type: ignore[arg-type]
        palette_pass=bool(payload.get("palette_pass", False)),
        fonts_pass=bool(payload.get("fonts_pass", False)),
        voice_pass=bool(payload.get("voice_pass", False)),
        asset_pass=bool(payload.get("asset_pass", False)),
        notes=notes_tuple,
        diagnostic=payload.get("diagnostic") or {},
    )


async def invoke_darla_qa(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str] = None,
    intake_text: Optional[str] = None,
    memory_block: str = "",
    transport: Any = None,
) -> BrandAttestation:
    """Invoke Darla and return a structured BrandAttestation.

    Loads the rendered output content + the tenant brand profile,
    asks Darla to score, parses the verdict, emits the appropriate
    `darla.qa_*` audit event, returns the attestation for the
    chain runtime / caller to act on.

    Caller responsibility:
      - On `pass`: proceed to `deliver` step (Paul).
      - On `needs_revision`: return to render step with notes;
        respect 2-cycle cap.
      - On `block`: halt publish, surface operator-actionable
        transition, open new execution_cycle.
    """
    # Load output package content (the thing being QA'd).
    pkg_row = await conn.fetchrow(
        """
        SELECT title, summary, content_blocks::text AS content_blocks_json
        FROM output_packages
        WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        output_package_id,
        client_id,
    )
    if pkg_row is None:
        raise ValueError(f"output_package_id not found in tenant: {output_package_id}")

    brand_profile_text = await _load_brand_profile_text(conn, client_id=client_id)

    # Build Darla's intake. The render preview is the package's
    # content; the brand profile is the scoring rubric.
    darla_intake_parts: list[str] = []
    if intake_text:
        darla_intake_parts.append(f"WO INTENT: {intake_text}")
    if pkg_row["title"]:
        darla_intake_parts.append(f"PACKAGE TITLE: {pkg_row['title']}")
    if pkg_row["summary"]:
        darla_intake_parts.append(f"PACKAGE SUMMARY: {pkg_row['summary']}")
    content_blocks_json = pkg_row["content_blocks_json"] or "{}"
    darla_intake_parts.append(f"PACKAGE CONTENT:\n{content_blocks_json[:4000]}")
    if brand_profile_text:
        darla_intake_parts.append(f"\nBRAND PROFILE TO SCORE AGAINST:\n{brand_profile_text}")
    else:
        darla_intake_parts.append(
            "\nBRAND PROFILE: (none authored — return verdict='pass' as no brand criteria apply)"
        )
    darla_intake = "\n\n".join(darla_intake_parts)

    envelope = await invoke_tier_2(
        conn,
        role="darla_tier_2",
        intake_text=darla_intake,
        content_blocks={
            "qa_mode": "brand_attestation",
            "package_id": output_package_id,
        },
        work_order_id=work_order_id,
        client_id=client_id,
        actor_user_id=actor_user_id,
        memory_block=memory_block,
        transport=transport,
    )

    attestation = _parse_attestation(envelope)

    audit_event = _AUDIT_EVENTS_BY_VERDICT[attestation.overall]
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event=audit_event,
        target_type="output_package",
        target_id=output_package_id,
        metadata={
            "verdict": attestation.overall,
            "palette_pass": attestation.palette_pass,
            "fonts_pass": attestation.fonts_pass,
            "voice_pass": attestation.voice_pass,
            "asset_pass": attestation.asset_pass,
            "note_count": len(attestation.notes),
            "notes": list(attestation.notes)[:8],  # first 8 only; full set on the row
            "work_order_id": work_order_id,
        },
    )

    return attestation
