"""CLI entry point for the Python DigiFLOW router.

Used by the TS parity contract test
(`tests/contract/digiflow-routing-parity.test.ts`). Reads one JSON
packet on stdin and writes the RouteDecision JSON on stdout.
"""

from __future__ import annotations

import json
import sys

from digiflow.intake import route_intake


def main() -> int:
    try:
        packet = json.load(sys.stdin)
        decision = route_intake(packet)
        json.dump(decision, sys.stdout)
        return 0
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"DigiflowRouterError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
