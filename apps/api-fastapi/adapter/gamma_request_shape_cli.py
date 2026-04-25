"""CLI entry point for Gamma request-shape parity.

Reads a JSON envelope on stdin:
  {"op": "build_request" | "parse_submit" | "parse_poll",
   "input": { ... op-specific payload ... },
   "generationId"?: "..."  // parse_poll only
  }

Writes the operation's JSON output to stdout. Exits non-zero with the
exception message on stderr.
"""

from __future__ import annotations

import json
import sys

from adapter.gamma_request_shape import (
    GammaPackageInvalidError,
    GammaSubmitResponseInvalidError,
    build_gamma_request_body,
    poll_response_from_json,
    shape_input_from_json,
    shape_to_json,
    submit_response_from_json,
)


def main() -> int:
    try:
        envelope = json.load(sys.stdin)
        op = envelope["op"]
        if op == "build_request":
            shape = build_gamma_request_body(
                shape_input_from_json(envelope["input"])
            )
            json.dump(shape_to_json(shape), sys.stdout)
        elif op == "parse_submit":
            json.dump(submit_response_from_json(envelope["input"]), sys.stdout)
        elif op == "parse_poll":
            json.dump(
                poll_response_from_json(
                    envelope["generationId"], envelope["input"]
                ),
                sys.stdout,
            )
        else:
            print(f"unknown op: {op}", file=sys.stderr)
            return 2
        return 0
    except GammaPackageInvalidError as exc:
        print(f"GammaPackageInvalidError: {exc}", file=sys.stderr)
        return 10
    except GammaSubmitResponseInvalidError as exc:
        print(f"GammaSubmitResponseInvalidError: {exc}", file=sys.stderr)
        return 11
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"RequestShapeError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
