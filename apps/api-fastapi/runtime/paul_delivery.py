"""Loop CAP-D Φ.5 — Paul intelligent delivery layer.

Paul wraps the mechanical adapter call (`dispatch_gamma_for_package`
today; CAP-F sandbox/Stitch/Figma/21st-Magic adapters later) with an
LLM step that owns:

  - template variant selection — when a tenant has multiple
    template_profiles for the requested output_kind (multi-template
    Klear scenario, Q-PG-9), Paul picks the one whose
    content_contract.label best matches the package's intent.
  - candidate-review policy enforcement — when policy carries
    candidate_review semantics, Paul picks among N rendered candidates.
  - fallback adapter selection — when primary adapter fails or is
    gated by missing credentials (Stitch credentials missing, Figma
    not provisioned), Paul falls through to the next adapter in the
    chain config.
  - failure recovery — Paul can request a retry of the render step
    with revised parameters before giving up.

Architectural locks honored (per CAP v0.3.0):
  - P5   — every external surface reached through a Paul-led LLM step.
  - D4   — locked: full LLM Paul from day one (no stub mode).
  - D6   — Paul reads `client_brand_profiles.template_handles_json`
           for the variant choice space.

CAP-D scope:
  This module ships the helper. Wire-in to chain step execution
  (`execute_step_run` recognizing step_key="deliver") happens in
  this same loop. Paul currently has only Gamma to dispatch to
  (sandbox/Stitch/Figma/21st adapters land in CAP-F Φ.9); the
  decision shape is established now so CAP-F adapters slot in
  without changing Paul's contract.

Audit:
  Always emits exactly one `paul.delivery_decided` per invocation.
  May additionally emit:
    paul.template_variant_chosen      — when multi-template
                                        disambiguation fired
    paul.candidate_selected           — when candidate-review policy
                                        was active
    paul.fallback_adapter_invoked     — when primary adapter was
                                        unavailable / failed
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import asyncpg

from authz.audit_writer import write_audit_row

from .tier_2_subagents import invoke_tier_2


DeliveryDecisionOutcome = Literal[
    "primary_dispatch",
    "fallback_dispatch",
    "blocked",
]


@dataclass(frozen=True)
class PaulDecision:
    """Structured Paul output. Persisted on workflow_step_runs.output
    when the step_key is `deliver`. Read by the chain runtime to
    actually trigger the adapter call (or to halt with operator
    notice when outcome=blocked)."""

    outcome: DeliveryDecisionOutcome
    template_profile_id: Optional[str]
    adapter_key: str
    fallback_adapter_keys: tuple[str, ...] = field(default_factory=tuple)
    decision_reason: str = ""
    candidate_choice: Optional[str] = None  # candidate_id when picked
    diagnostic: dict[str, Any] = field(default_factory=dict)


async def _load_brand_template_choices(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    output_kind: str,
) -> list[dict[str, Any]]:
    """Look up the tenant's available template_profiles for a given
    output_kind via the brand profile's `template_handles_json`. Returns
    the resolved template_profile rows (id + profile_key + label)
    Paul picks among."""
    profile_row = await conn.fetchrow(
        """
        SELECT template_handles_json::text AS template_handles_json
        FROM client_brand_profiles
        WHERE client_id = $1::uuid
        """,
        client_id,
    )
    if profile_row is None:
        return []
    try:
        handles = json.loads(profile_row["template_handles_json"] or "{}")
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(handles, dict):
        return []
    ids = handles.get(output_kind) or []
    if not isinstance(ids, list) or not ids:
        return []

    rows = await conn.fetch(
        """
        SELECT id::text                  AS id,
               profile_key,
               external_ref,
               content_contract::text    AS content_contract_json
        FROM template_profiles
        WHERE client_id = $1::uuid
          AND id = ANY($2::uuid[])
          AND status = 'active'
        ORDER BY profile_key
        """,
        client_id,
        ids,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        cc: Any = {}
        if r["content_contract_json"]:
            try:
                cc = json.loads(r["content_contract_json"])
            except (json.JSONDecodeError, ValueError):
                cc = {}
        label = (cc or {}).get("label") if isinstance(cc, dict) else None
        out.append(
            {
                "id": r["id"],
                "profile_key": r["profile_key"],
                "external_ref": r["external_ref"],
                "label": label or r["profile_key"],
            }
        )
    return out


def _parse_decision(result_or_envelope: Any, default_adapter_key: str) -> PaulDecision:
    """Parse Paul's structured output into a PaulDecision. Falls back
    to a `blocked` outcome if the LLM returned something off-contract —
    failing closed because dispatch should not happen on uncertain
    intent.

    Accepts either a `Tier2InvocationResult` or a bare
    `Tier2OutputEnvelope`. Reads structured fields from
    `envelope.metadata` jsonb (standard Tier-2 metadata channel)."""
    payload: dict[str, Any] = {}
    envelope = getattr(result_or_envelope, "output_envelope", result_or_envelope)
    metadata = getattr(envelope, "metadata", None)
    if isinstance(metadata, dict):
        payload = metadata
    elif isinstance(result_or_envelope, dict):
        payload = result_or_envelope.get("metadata") or result_or_envelope

    outcome = payload.get("outcome")
    if outcome not in ("primary_dispatch", "fallback_dispatch", "blocked"):
        return PaulDecision(
            outcome="blocked",
            template_profile_id=None,
            adapter_key=default_adapter_key,
            fallback_adapter_keys=(),
            decision_reason="Paul output did not match the structured contract; failing closed.",
            diagnostic={"raw_payload": str(payload)[:500]},
        )

    fallback_raw = payload.get("fallback_adapter_keys") or []
    if isinstance(fallback_raw, list):
        fallbacks = tuple(str(x) for x in fallback_raw if x)
    else:
        fallbacks = ()

    return PaulDecision(
        outcome=outcome,  # type: ignore[arg-type]
        template_profile_id=(
            str(payload["template_profile_id"])
            if payload.get("template_profile_id")
            else None
        ),
        adapter_key=str(payload.get("adapter_key") or default_adapter_key),
        fallback_adapter_keys=fallbacks,
        decision_reason=str(payload.get("decision_reason") or ""),
        candidate_choice=(
            str(payload["candidate_choice"])
            if payload.get("candidate_choice")
            else None
        ),
        diagnostic=payload.get("diagnostic") or {},
    )


async def invoke_paul_delivery(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
    output_kind: str,
    primary_adapter_key: str = "gamma",
    fallback_adapter_keys: Optional[list[str]] = None,
    attestation_summary: Optional[dict[str, Any]] = None,
    work_order_id: Optional[str] = None,
    intake_text: Optional[str] = None,
    memory_block: str = "",
    transport: Any = None,
) -> PaulDecision:
    """Invoke Paul and return a structured delivery decision.

    Caller responsibility:
      - On `outcome=primary_dispatch`: call the adapter identified
        by `decision.adapter_key` with `decision.template_profile_id`.
      - On `outcome=fallback_dispatch`: call the first fallback in
        `fallback_adapter_keys` (Paul has already factored the
        primary's unavailability into the decision).
      - On `outcome=blocked`: halt publish, surface operator-actionable
        transition with `decision.decision_reason` + diagnostic.
    """
    # Load package + variant choice space.
    pkg_row = await conn.fetchrow(
        """
        SELECT title,
               summary,
               output_kind::text       AS output_kind,
               template_profile_id::text AS template_profile_id,
               content_blocks::text    AS content_blocks_json
        FROM output_packages
        WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        output_package_id,
        client_id,
    )
    if pkg_row is None:
        raise ValueError(f"output_package_id not found in tenant: {output_package_id}")

    variant_choices = await _load_brand_template_choices(
        conn, client_id=client_id, output_kind=output_kind
    )

    fallback_keys = list(fallback_adapter_keys or [])

    # Build Paul's intake.
    paul_intake_parts: list[str] = []
    if intake_text:
        paul_intake_parts.append(f"WO INTENT: {intake_text}")
    paul_intake_parts.append(f"REQUESTED OUTPUT KIND: {output_kind}")
    paul_intake_parts.append(f"PRIMARY ADAPTER: {primary_adapter_key}")
    if fallback_keys:
        paul_intake_parts.append(
            f"FALLBACK ADAPTERS (in order): {', '.join(fallback_keys)}"
        )
    if pkg_row["template_profile_id"]:
        paul_intake_parts.append(
            f"PACKAGE-CARRIED TEMPLATE: {pkg_row['template_profile_id']}"
        )
    if variant_choices:
        choices_text = "\n".join(
            f"  - {c['id']} = {c['profile_key']} ({c['label']}); external_ref={c['external_ref']}"
            for c in variant_choices
        )
        paul_intake_parts.append(
            f"AVAILABLE TEMPLATE VARIANTS for output_kind={output_kind}:\n{choices_text}"
        )
    else:
        paul_intake_parts.append(
            f"AVAILABLE TEMPLATE VARIANTS: (none registered for output_kind={output_kind} on this tenant)"
        )
    if attestation_summary is not None:
        paul_intake_parts.append(
            f"DARLA ATTESTATION SUMMARY: {json.dumps(attestation_summary)[:600]}"
        )
    if pkg_row["title"]:
        paul_intake_parts.append(f"PACKAGE TITLE: {pkg_row['title']}")
    if pkg_row["summary"]:
        paul_intake_parts.append(f"PACKAGE SUMMARY: {pkg_row['summary']}")

    paul_intake = "\n\n".join(paul_intake_parts)

    envelope = await invoke_tier_2(
        conn,
        role="paul_tier_2",
        intake_text=paul_intake,
        content_blocks={
            "delivery_mode": "intelligent",
            "package_id": output_package_id,
            "output_kind": output_kind,
            "primary_adapter_key": primary_adapter_key,
            "fallback_adapter_keys": fallback_keys,
        },
        work_order_id=work_order_id,
        client_id=client_id,
        actor_user_id=actor_user_id,
        memory_block=memory_block,
        transport=transport,
    )

    decision = _parse_decision(envelope, default_adapter_key=primary_adapter_key)

    # Always-on audit: paul.delivery_decided.
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="paul.delivery_decided",
        target_type="output_package",
        target_id=output_package_id,
        metadata={
            "outcome": decision.outcome,
            "template_profile_id": decision.template_profile_id,
            "adapter_key": decision.adapter_key,
            "fallback_adapter_keys": list(decision.fallback_adapter_keys),
            "decision_reason": decision.decision_reason,
            "candidate_choice": decision.candidate_choice,
            "work_order_id": work_order_id,
            "output_kind": output_kind,
        },
    )

    # Conditional audits.
    # paul.template_variant_chosen — fires when there were >1 options
    # and Paul picked one (i.e. multi-template disambiguation).
    if len(variant_choices) > 1 and decision.template_profile_id:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="paul.template_variant_chosen",
            target_type="output_package",
            target_id=output_package_id,
            metadata={
                "chosen_template_profile_id": decision.template_profile_id,
                "available_template_profile_ids": [c["id"] for c in variant_choices],
                "decision_reason": decision.decision_reason,
            },
        )

    # paul.candidate_selected — fires when candidate_choice is set.
    if decision.candidate_choice:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="paul.candidate_selected",
            target_type="output_package",
            target_id=output_package_id,
            metadata={
                "candidate_choice": decision.candidate_choice,
                "decision_reason": decision.decision_reason,
            },
        )

    # paul.fallback_adapter_invoked — fires when outcome is fallback_dispatch.
    if decision.outcome == "fallback_dispatch":
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="paul.fallback_adapter_invoked",
            target_type="output_package",
            target_id=output_package_id,
            metadata={
                "primary_adapter_key": primary_adapter_key,
                "fallback_adapter_key": decision.adapter_key,
                "decision_reason": decision.decision_reason,
            },
        )

    return decision
