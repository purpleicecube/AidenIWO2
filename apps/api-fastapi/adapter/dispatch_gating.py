"""Loop 9 Phase 9.1 — Python mirror of ``packages/contracts/adapter/dispatch_gating.ts``.

Pure function. Byte-for-byte parity with the TypeScript canonical is
enforced by ``tests/contract/dispatch-gating-parity.test.ts``, which
spawns ``dispatch_gating_cli.py`` and diffs the JSON output.

See the TS file header for the design rationale (dual first-live-
invocation gate; candidate-review deliberately not used).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, Literal, Optional, Union

LiveGateReason = Literal[
    "live_disabled",
    "credential_missing",
    "first_invocation_pending",
]


@dataclass(frozen=True)
class LiveGateInput:
    is_live: bool
    adapter_key: str
    env_flag_name: Optional[str]
    env_flag_value: Optional[str]
    has_credential: bool
    credential_first_invocation_confirmed_at: Optional[str]


@dataclass(frozen=True)
class LiveGateAllow:
    allow: Literal[True] = True


@dataclass(frozen=True)
class LiveGateRefuse:
    reason: LiveGateReason
    detail: str
    allow: Literal[False] = False


LiveGateDecision = Union[LiveGateAllow, LiveGateRefuse]


def decide_live_gate(inp: LiveGateInput) -> LiveGateDecision:
    """Pure gating decision. Mirrors ``decideLiveGate`` in the TS canonical.

    The string formatting below must stay byte-identical with the TS
    version — the parity test diffs ``.detail`` as-is.
    """
    if not inp.is_live:
        return LiveGateAllow()

    if not inp.env_flag_name:
        return LiveGateRefuse(
            reason="live_disabled",
            detail=(
                f"adapter {inp.adapter_key} is live but describe() "
                "returned no envFlagName"
            ),
        )

    if inp.env_flag_value != "true":
        shown = (
            "<unset>"
            if inp.env_flag_value is None
            else json.dumps(inp.env_flag_value)
        )
        return LiveGateRefuse(
            reason="live_disabled",
            detail=f'{inp.env_flag_name} is not "true" (got {shown})',
        )

    if not inp.has_credential:
        return LiveGateRefuse(
            reason="credential_missing",
            detail=(
                f"no adapter_credentials row for adapter={inp.adapter_key}"
            ),
        )

    if not inp.credential_first_invocation_confirmed_at:
        return LiveGateRefuse(
            reason="first_invocation_pending",
            detail=(
                f"adapter {inp.adapter_key} credential has no "
                "first_invocation_confirmed_at; admin must confirm via "
                "POST /adapter_credentials/{id}/confirm_first_invocation"
            ),
        )

    return LiveGateAllow()


# ──────────────────────────────────────────────────────────────────────
# JSON (de)serialization — must stay symmetric with the TS CLI.
# ──────────────────────────────────────────────────────────────────────


def from_json(raw: dict) -> LiveGateInput:
    """Parse a TS-shaped input object (camelCase keys)."""
    return LiveGateInput(
        is_live=bool(raw["isLive"]),
        adapter_key=str(raw["adapterKey"]),
        env_flag_name=_opt_str(raw.get("envFlagName")),
        env_flag_value=_opt_env_flag_value(raw.get("envFlagValue")),
        has_credential=bool(raw["hasCredential"]),
        credential_first_invocation_confirmed_at=_opt_str(
            raw.get("credentialFirstInvocationConfirmedAt")
        ),
    )


def to_json(decision: LiveGateDecision) -> dict:
    """Serialize to the exact TS-shaped output object."""
    if decision.allow:
        return {"allow": True}
    return {
        "allow": False,
        "reason": decision.reason,
        "detail": decision.detail,
    }


def _opt_str(v: object) -> Optional[str]:
    if v is None:
        return None
    return str(v)


def _opt_env_flag_value(v: object) -> Optional[str]:
    # TS treats `undefined` and `null` identically for envFlagValue —
    # both become `null` on the JSON wire. Python receives `None` for
    # both; preserve that as-is.
    if v is None:
        return None
    return str(v)


DISPATCH_GATING_CONTRACT_VERSION: Final[str] = "v0"
