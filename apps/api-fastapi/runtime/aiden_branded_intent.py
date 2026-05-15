"""Loop CAP-E Φ.8 — Aiden Tier 1 branded-intent classification.

Deterministic post-LLM detector that:

  1. Looks at the operator intake + WO `requested_outputs.template_profile_id`
     and decides whether this is a BRANDED request (vs unbranded /
     internal / conversational).
  2. Detects the requested `output_kind` from intake when not already
     explicit (reuses the existing template_resolver heuristic).
  3. Detects `design_input_source` from intake keywords (Stitch /
     Figma / 21st-Magic / null).
  4. When tenant has multiple `template_profile` rows for the
     detected output_kind, picks the best by intake-keyword match
     (`selected_template_profile_id`).
  5. Looks up the matching chain in `output_surface_routes` (Φ.7).
  6. When all signals align → caller flips `AidenDecision.decision_kind`
     to "workflow_brief" with the resolved `workflow_template_key`.

Architectural locks honored (per CAP v0.3.0):
  - P7    — Aiden Tier 1 distinguishes branded vs unbranded intent
            and disambiguates multi-template tenants. Detector is
            deterministic (not LLM-driven) so the routing decision is
            reproducible + auditable.
  - D8    — when branded intent matches a registry route, decision
            flips to workflow_brief. (D8 also locked: removed
            operator-block fallback — all branded surfaces have
            chains after CAP-C.)
  - D14   — multi-template disambiguation is Aiden-LLM with
            operator-picker fallback. CAP-E ships the deterministic
            keyword-scoring path; LLM disambiguation is the next-
            tightening lever (use existing template_resolver scoring
            since it already handles this surface).

Audit events (locked under LOOP_CAP_E_PHI8_AUDIT_EVENTS):
  aiden.branded_intent_detected         — always-on per dispatch where
                                          detector ran; metadata
                                          carries verdict + matched
                                          brand_terms
  aiden.multi_template_disambiguated    — when >1 template candidate
                                          existed and detector picked one
  aiden.template_clarification_requested — when intent is templated
                                          but detector cannot
                                          disambiguate; chat-side picker
                                          (Eta phase 1.6 pattern)
                                          takes over

Scope:
  This module ships the detector + registry lookup. Wire-in to
  routes/dispatch.py to override decision_kind for branded WOs
  happens in this same loop.

Firewall:
  Caller passes a tenant-scoped FastAPI conn; reads use explicit
  `client_id = $1::uuid` predicates against client_brand_profiles +
  template_profiles. The output_surface_routes table is global (no
  RLS); reads against it carry no client_id predicate (registry is
  shared).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import asyncpg

from authz.audit_writer import write_audit_row

from .template_resolver import (
    TemplateChoice,
    _detect_output_kind,
    _norm,
    _score_profile,
    load_active_templates,
)


_DESIGN_INPUT_TOKENS: dict[str, tuple[str, ...]] = {
    "stitch": ("stitch", "stitch.google", "google stitch", "stitch design"),
    "figma": ("figma", "figma file", "figma frame", "figma design"),
    "twentyfirst": (
        "21st",
        "21st-magic",
        "21stmagic",
        "21st century",
        "21stcomponent",
        "magic mcp",
    ),
}


@dataclass(frozen=True)
class BrandedIntent:
    """Output of the deterministic branded-intent detector."""

    is_branded: bool
    detected_brand_keywords: tuple[str, ...]
    detected_output_kind: Optional[str]
    detected_design_input_source: Optional[str]
    selected_template_profile_id: Optional[str]
    selected_template_profile_key: Optional[str]
    template_candidates: tuple[dict, ...]
    workflow_key: Optional[str]
    primary_adapter_key: Optional[str]
    fallback_adapter_keys: tuple[str, ...]
    needs_clarification: bool = False
    diagnostic: dict[str, Any] = field(default_factory=dict)


def _detect_design_input_source(intake_norm: str) -> Optional[str]:
    """Match design-input-source tokens against the intake. Returns
    the highest-token-count source, or None when nothing matches."""
    best_kind: Optional[str] = None
    best_hits = 0
    for kind, tokens in _DESIGN_INPUT_TOKENS.items():
        hits = sum(1 for tok in tokens if tok in intake_norm)
        if hits > best_hits:
            best_kind = kind
            best_hits = hits
    return best_kind


async def _load_brand_terms_and_profile_id(
    conn: asyncpg.Connection, *, client_id: str
) -> tuple[tuple[str, ...], Optional[str]]:
    """Load the tenant's `brand_terms[]` array + brand profile id.
    Returns ((), None) when the tenant has no brand profile row."""
    row = await conn.fetchrow(
        """
        SELECT id::text AS id, brand_terms
        FROM client_brand_profiles
        WHERE client_id = $1::uuid
        """,
        client_id,
    )
    if row is None:
        return (tuple(), None)
    terms = row["brand_terms"] or []
    return (tuple(t for t in terms if t), row["id"])


def _detect_brand_keyword_matches(
    intake: str, brand_terms: tuple[str, ...]
) -> tuple[str, ...]:
    """Case-insensitive substring match of brand_terms against intake."""
    if not brand_terms or not intake:
        return tuple()
    intake_lower = intake.lower()
    matched: list[str] = []
    seen_lower: set[str] = set()
    for term in brand_terms:
        tl = term.lower()
        if tl in seen_lower:
            continue
        if tl in intake_lower:
            matched.append(term)
            seen_lower.add(tl)
    return tuple(matched)


async def _lookup_route(
    conn: asyncpg.Connection,
    *,
    output_kind: str,
    is_branded: bool,
    design_input_source: Optional[str],
) -> Optional[dict[str, Any]]:
    """Look up the chain in `output_surface_routes` for a given tuple.
    Returns None when no route exists for this combination (caller
    falls through to existing single-shot path; per D8 lock, branded
    surfaces should ALL have chains after CAP-C)."""
    row = await conn.fetchrow(
        """
        SELECT workflow_key,
               primary_adapter_key,
               fallback_adapter_keys
        FROM output_surface_routes
        WHERE output_kind = $1
          AND is_branded = $2
          AND COALESCE(design_input_source, 'none') = COALESCE($3, 'none')
        LIMIT 1
        """,
        output_kind,
        is_branded,
        design_input_source,
    )
    if row is None:
        return None
    return {
        "workflow_key": row["workflow_key"],
        "primary_adapter_key": row["primary_adapter_key"],
        "fallback_adapter_keys": tuple(row["fallback_adapter_keys"] or ()),
    }


def _select_template_candidate(
    intake: str,
    candidates: list[TemplateChoice],
) -> tuple[Optional[TemplateChoice], list[TemplateChoice], bool]:
    """Pick the best template_profile from a candidate list using the
    same keyword scorer template_resolver uses for chat-side resolution.
    Returns (chosen | None, all_candidates_for_audit, needs_clarification).

    needs_clarification=True when:
      - 0 candidates → caller should fall back to default template handling
      - >1 candidates with no clear winner (top-2 within 1 point) → ask operator
    """
    if not candidates:
        return (None, [], False)
    if len(candidates) == 1:
        return (candidates[0], list(candidates), False)
    intake_norm = _norm(intake)
    scored: list[tuple[int, TemplateChoice]] = []
    for tpl in candidates:
        score, _ = _score_profile(tpl.profile_key, intake_norm, _norm(tpl.label))
        scored.append((score, tpl))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top_tpl = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -1
    # Tie-break threshold: top must beat second by at least 2 points.
    if top_score >= 5 and (top_score - second_score) >= 2:
        return (top_tpl, list(candidates), False)
    # Ambiguous — caller should request clarification.
    return (None, list(candidates), True)


async def _load_tenant_templates_for_kind(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    output_kind: str,
) -> list[TemplateChoice]:
    """Return active template_profiles for the tenant matching the
    requested output_kind. Reuses the existing `load_active_templates`
    + filters by output_kind to keep one source of truth."""
    all_templates = await load_active_templates(conn, client_id=client_id)
    return [t for t in all_templates if t.output_kind == output_kind]


async def detect_branded_intent(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    intake_text: str,
    actor_user_id: Optional[str],
    explicit_template_profile_id: Optional[str] = None,
    explicit_output_kind: Optional[str] = None,
) -> BrandedIntent:
    """Run the deterministic branded-intent detector + registry lookup.

    Always emits exactly one `aiden.branded_intent_detected` audit row.
    May additionally emit `aiden.multi_template_disambiguated` (when
    >1 template candidates existed and detector picked one) or
    `aiden.template_clarification_requested` (when intent is templated
    but detector cannot disambiguate).

    Returns a `BrandedIntent` carrying the verdict + supporting fields.
    Caller (dispatch.py) decides whether to override `decision_kind`
    based on `is_branded` + `workflow_key`.
    """
    intake_norm = _norm(intake_text)
    brand_terms, _brand_profile_id = await _load_brand_terms_and_profile_id(
        conn, client_id=client_id
    )

    matched_terms = _detect_brand_keyword_matches(intake_text, brand_terms)
    has_explicit_template = explicit_template_profile_id is not None
    is_branded = bool(matched_terms) or has_explicit_template

    detected_kind: Optional[str] = (
        explicit_output_kind or _detect_output_kind(intake_norm)
    )
    detected_design = _detect_design_input_source(intake_norm)

    # Multi-template disambiguation.
    selected_id: Optional[str] = explicit_template_profile_id
    selected_key: Optional[str] = None
    candidates_payload: list[dict] = []
    disambiguation_fired = False
    needs_clarification = False

    if is_branded and detected_kind and not selected_id:
        candidates = await _load_tenant_templates_for_kind(
            conn, client_id=client_id, output_kind=detected_kind
        )
        candidates_payload = [
            {
                "id": c.template_profile_id,
                "profile_key": c.profile_key,
                "label": c.label,
                "output_kind": c.output_kind,
            }
            for c in candidates
        ]
        chosen, _all, needs_clar = _select_template_candidate(
            intake_text, candidates
        )
        if chosen is not None:
            selected_id = chosen.template_profile_id
            selected_key = chosen.profile_key
            disambiguation_fired = len(candidates) > 1
        else:
            needs_clarification = needs_clar

    elif is_branded and selected_id:
        # Operator (or upstream resolver) already picked a template.
        # Still surface the candidate set for diagnostic.
        if detected_kind:
            candidates = await _load_tenant_templates_for_kind(
                conn, client_id=client_id, output_kind=detected_kind
            )
            candidates_payload = [
                {
                    "id": c.template_profile_id,
                    "profile_key": c.profile_key,
                    "label": c.label,
                    "output_kind": c.output_kind,
                }
                for c in candidates
            ]

    # Registry lookup.
    workflow_key: Optional[str] = None
    primary_adapter_key: Optional[str] = None
    fallback_adapter_keys: tuple[str, ...] = ()
    if is_branded and detected_kind:
        route = await _lookup_route(
            conn,
            output_kind=detected_kind,
            is_branded=True,
            design_input_source=detected_design,
        )
        if route is not None:
            workflow_key = route["workflow_key"]
            primary_adapter_key = route["primary_adapter_key"]
            fallback_adapter_keys = route["fallback_adapter_keys"]

    intent = BrandedIntent(
        is_branded=is_branded,
        detected_brand_keywords=matched_terms,
        detected_output_kind=detected_kind,
        detected_design_input_source=detected_design,
        selected_template_profile_id=selected_id,
        selected_template_profile_key=selected_key,
        template_candidates=tuple(candidates_payload),
        workflow_key=workflow_key,
        primary_adapter_key=primary_adapter_key,
        fallback_adapter_keys=fallback_adapter_keys,
        needs_clarification=needs_clarification,
        diagnostic={
            "explicit_template_profile_id": explicit_template_profile_id,
            "explicit_output_kind": explicit_output_kind,
            "tenant_brand_terms_count": len(brand_terms),
        },
    )

    # Always-on audit: aiden.branded_intent_detected.
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="aiden.branded_intent_detected",
        target_type="dispatch_intent",
        target_id=None,
        metadata={
            "is_branded": intent.is_branded,
            "detected_brand_keywords": list(intent.detected_brand_keywords),
            "detected_output_kind": intent.detected_output_kind,
            "detected_design_input_source": intent.detected_design_input_source,
            "selected_template_profile_id": intent.selected_template_profile_id,
            "selected_template_profile_key": intent.selected_template_profile_key,
            "candidate_count": len(intent.template_candidates),
            "workflow_key": intent.workflow_key,
            "needs_clarification": intent.needs_clarification,
        },
    )

    if disambiguation_fired:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="aiden.multi_template_disambiguated",
            target_type="dispatch_intent",
            target_id=None,
            metadata={
                "selected_template_profile_id": intent.selected_template_profile_id,
                "selected_template_profile_key": intent.selected_template_profile_key,
                "candidate_count": len(intent.template_candidates),
                "candidate_keys": [c["profile_key"] for c in intent.template_candidates],
                "detected_output_kind": intent.detected_output_kind,
            },
        )

    if needs_clarification:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="aiden.template_clarification_requested",
            target_type="dispatch_intent",
            target_id=None,
            metadata={
                "candidate_count": len(intent.template_candidates),
                "candidate_keys": [c["profile_key"] for c in intent.template_candidates],
                "detected_output_kind": intent.detected_output_kind,
            },
        )

    return intent
