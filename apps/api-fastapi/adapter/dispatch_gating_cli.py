"""CLI entry point for the Python live-gate decision.

Used by the TS parity contract test
(``tests/contract/dispatch-gating-parity.test.ts``). Reads a JSON input
on stdin, writes JSON output on stdout. Exits non-zero with the
exception message on stderr.
"""

from __future__ import annotations

import json
import sys

from adapter.dispatch_gating import decide_live_gate, from_json, to_json


def main() -> int:
    try:
        inp = from_json(json.load(sys.stdin))
        out = to_json(decide_live_gate(inp))
        json.dump(out, sys.stdout)
        return 0
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"DispatchGatingError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
