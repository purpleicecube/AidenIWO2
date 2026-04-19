"""Loop 3 Phase 3 — DigiFLOW intake contract + routing (Python parity).

Byte-identical output to `packages/contracts/digiflow/routing.ts`. The
TS side is the reference; parity is enforced by
`tests/contract/digiflow-routing-parity.test.ts` across six fixture
packets.

Rules (CODEX response packet §2):
  1. If requested_execution_mode is 'wo' or 'wf', honor it.
  2. If recurrence.kind is present and not 'once', route WF.
  3. Otherwise if desired_outputs has at least one entry, route WO.
  4. Ambiguous (no outputs, no explicit mode, no recurrence) →
     needs_clarification.

Policy (IWO3_LOOP_3_APPROVAL_DECISIONS §Q4 `contract_only`):
  - No FastAPI endpoint in Loop 3. This module ships validation +
    routing only. Endpoint lands in Loop 7.
  - No DB writes. Pure functions.
"""

from __future__ import annotations

from typing import Any, TypedDict


class RouteDecision(TypedDict):
    kind: str  # "wo" | "wf" | "needs_clarification"
    rationale: str


def route_intake(packet: dict[str, Any]) -> RouteDecision:
    mode = packet.get("requested_execution_mode") or "auto"

    if mode == "wo":
        return {
            "kind": "wo",
            "rationale": "requested_execution_mode='wo' — explicit override",
        }
    if mode == "wf":
        return {
            "kind": "wf",
            "rationale": "requested_execution_mode='wf' — explicit override",
        }

    recurrence = packet.get("recurrence") or {}
    recurrence_kind = recurrence.get("kind")
    has_recurrence = bool(recurrence_kind and recurrence_kind != "once")

    if has_recurrence:
        return {
            "kind": "wf",
            "rationale": f"recurrence.kind='{recurrence_kind}' → repeatable workflow",
        }

    outputs = packet.get("desired_outputs") or []
    if len(outputs) == 1:
        return {"kind": "wo", "rationale": "single one-time output, no recurrence"}
    if len(outputs) > 1:
        return {
            "kind": "wo",
            "rationale": (
                f"{len(outputs)} one-time outputs, single run → "
                "WO with multiple output packages"
            ),
        }

    return {
        "kind": "needs_clarification",
        "rationale": (
            "ambiguous — no desired_outputs, no recurrence, "
            "no explicit execution mode"
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# Minimal Python validation (parity with TS Zod rules most likely to
# diverge if someone forgets to touch both sides)
# ──────────────────────────────────────────────────────────────────────

CREDENTIAL_REF_PREFIX = "credential_ref:"


def validate_intake_packet(packet: dict[str, Any]) -> list[str]:
    """Return a list of error strings. Empty list = valid.

    Covers the subset of Zod rules that fixture tests assert on the
    Python side. Full Zod parity lives in TS; Python mirrors the
    cross-loop invariants (tenant, credential_ref, outputs).
    """
    errors: list[str] = []

    if packet.get("schema_version") != "v0":
        errors.append("schema_version: must be 'v0'")
    if packet.get("source_system") != "digiflow":
        errors.append("source_system: must be 'digiflow'")
    if not (packet.get("client_designation") or packet.get("client_id")):
        errors.append(
            "either client_designation or client_id must be present"
        )

    requester = packet.get("requester") or {}
    if requester.get("kind") not in ("user", "service"):
        errors.append("requester.kind: must be 'user' or 'service'")

    title = packet.get("title") or ""
    if not title.strip():
        errors.append("title: must be non-empty")
    objective = packet.get("objective") or ""
    if not objective.strip():
        errors.append("objective: must be non-empty")

    outputs = packet.get("desired_outputs") or []
    if not isinstance(outputs, list) or len(outputs) == 0:
        errors.append("desired_outputs: must have at least one entry")

    assets = packet.get("assets") or []
    for idx, asset in enumerate(assets):
        cref = asset.get("credential_ref")
        if cref is not None and not isinstance(cref, str):
            errors.append(
                f"assets[{idx}].credential_ref: must be string or null"
            )
        elif isinstance(cref, str) and not cref.startswith(
            CREDENTIAL_REF_PREFIX
        ):
            errors.append(
                f"assets[{idx}].credential_ref: must start with 'credential_ref:' or be null"
            )

    recurrence = packet.get("recurrence")
    if recurrence:
        if recurrence.get("kind") == "custom" and not recurrence.get(
            "frequency"
        ):
            errors.append(
                "recurrence.frequency: required when recurrence.kind='custom'"
            )

    return errors
