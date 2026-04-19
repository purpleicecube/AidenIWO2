"""Loop 2 Phase 2 — IWO3 prompt-resolution service (Python parity mirror).

Byte-identical output to `packages/contracts/prompt/resolver.ts`. The TS
side is the reference; parity is enforced by
`tests/contract/prompt-resolver-parity.test.ts` across eight fixture
inputs.

Algorithm (must match TS):
  1. Collect present layers in order: base, product, profile, workflow,
     wo, override.text (if any).
  2. Normalize each layer:
       a. strip trailing spaces/tabs from each line (regex [ \\t]+$
          multi-line).
       b. strip leading + trailing whitespace from the result.
  3. Drop empty normalized pieces.
  4. Join with "\\n\\n".
  5. Strip leading + trailing whitespace from the final joined string.
  6. SHA-256 the UTF-8 bytes; hex digest = renderHash.

Policy (IWO3_LOOP_2_APPROVAL_DECISIONS §Q2, ADR-002):
  - override kind "safety" is HARD-REJECTED.
  - "external_send" passes through with requires_approval=True.
  - "style" and "profile_swap" pass through normally.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


class SafetyOverrideRejected(ValueError):
    def __init__(self) -> None:
        super().__init__(
            "Override rejected: safety/tenant/tool overrides are "
            "disallowed in v0 (IWO3_LOOP_2_APPROVAL_DECISIONS \u00a7Q2; "
            "ADR-002)."
        )


_TRAILING_WS_PER_LINE = re.compile(r"[ \t]+$", flags=re.MULTILINE)


def _normalize(text: str) -> str:
    return _TRAILING_WS_PER_LINE.sub("", text).strip()


def resolve_prompt(inp: dict[str, Any]) -> dict[str, Any]:
    override = inp.get("override")
    if override and override.get("kind") == "safety":
        raise SafetyOverrideRejected()

    layers = inp.get("layers", {})
    layer_ids = inp.get("layerIds", {})

    pieces: list[str] = []
    if "base" in layers:
        pieces.append(_normalize(layers["base"]))
    if "product" in layers:
        pieces.append(_normalize(layers["product"]))
    pieces.append(_normalize(layers["profile"]))
    if "workflow" in layers:
        pieces.append(_normalize(layers["workflow"]))
    if "wo" in layers:
        pieces.append(_normalize(layers["wo"]))
    if override:
        pieces.append(_normalize(override["text"]))

    non_empty = [p for p in pieces if p]
    rendered = "\n\n".join(non_empty).strip()
    render_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    requires_approval = bool(override and override.get("kind") == "external_send")

    out: dict[str, Any] = {
        "renderedText": rendered,
        "renderHash": render_hash,
        "layerIds": layer_ids,
        "requiresApproval": requires_approval,
    }
    if override:
        out["overrideRef"] = {
            "kind": override["kind"],
            "userId": override["userId"],
            "reason": override["reason"],
        }
    return out
