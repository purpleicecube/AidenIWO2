"""CLI entry point for the Python resolver.

Used by the TS parity contract test
(`tests/contract/prompt-resolver-parity.test.ts`). Reads a JSON input on
stdin, writes JSON output on stdout. Exits non-zero with the exception
message on stderr when `SafetyOverrideRejected` is raised.
"""

from __future__ import annotations

import json
import sys

from prompt.resolver import SafetyOverrideRejected, resolve_prompt


def main() -> int:
    try:
        inp = json.load(sys.stdin)
        out = resolve_prompt(inp)
        json.dump(out, sys.stdout)
        return 0
    except SafetyOverrideRejected as exc:
        print(f"SafetyOverrideRejected: {exc}", file=sys.stderr)
        return 10
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"ResolverError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
