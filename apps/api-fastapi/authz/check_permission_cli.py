"""CLI entry point for the Python authz decision function.

Used by the TS parity contract test
(`tests/contract/authz-parity.test.ts`). Reads one fixture JSON packet
on stdin and writes the decision JSON on stdout.

Input shape (matches fixture on disk):
    {
      "role": "operator" | null,
      "rolePermissions": ["work_order:create", ...],
      "userGrants": [{"permissionKey": "...", "grantType": "allow"|"deny"}, ...],
      "permission": "output_package:submit",
      "knownPermissions": ["..."]  # optional
    }

Output:
    {"allowed": bool, "reason": "<reason_literal>", "role": "<role|null>"}
"""

from __future__ import annotations

import json
import sys

from authz.check_permission import UserGrant, check_permission_decide


def main() -> int:
    try:
        packet = json.load(sys.stdin)
        grants = [
            UserGrant(
                permission_key=g["permissionKey"], grant_type=g["grantType"]
            )
            for g in packet.get("userGrants", [])
        ]
        decision = check_permission_decide(
            role=packet.get("role"),
            role_permissions=packet.get("rolePermissions", []),
            user_grants=grants,
            permission=packet["permission"],
            known_permissions=packet.get("knownPermissions"),
        )
        json.dump(decision.to_dict(), sys.stdout)
        return 0
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"AuthzCliError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
