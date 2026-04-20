"""CLI for the Python state-machine mirror.

Used by ``tests/contract/state-machine-parity.test.ts``. Dumps the
complete transition tables as JSON to stdout so the TS test can
compare byte-for-byte against the TS canonical tables.

Output shape:

    {
      "machines": {
        "work_order": [
          {"from": "pending", "to": "processing",
           "requires": ["work_order:submit"],
           "event": "work_order.transitioned"},
          ...
        ],
        "workflow": [...],
        ...
      }
    }
"""

from __future__ import annotations

import json
import sys

from contracts.state_machines import STATE_MACHINES


def main() -> int:
    payload = {
        "machines": {
            name: [t.to_dict() for t in table]
            for name, table in STATE_MACHINES.items()
        }
    }
    json.dump(payload, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
