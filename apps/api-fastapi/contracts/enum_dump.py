"""CLI entry point for the Python enum mirror.

Used by ``tests/contract/enum-parity.test.ts``. Writes the complete
enum registry to stdout as JSON:

    {
      "enums": {
        "membership_role": ["owner", "admin", ...],
        ...
      }
    }

This output is compared byte-for-byte against the TS snapshot at
``tests/fixtures/contract-enums.snapshot.json`` (the ``dbEnums``
section). Any divergence fails CI.
"""

from __future__ import annotations

import json
import sys

from contracts.enums import ALL_ENUMS


def main() -> int:
    payload = {
        "enums": {name: list(values) for name, values in ALL_ENUMS.items()},
    }
    json.dump(payload, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
