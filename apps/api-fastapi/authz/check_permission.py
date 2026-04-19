"""Loop 4 Phase 2 — pure permission-decision function (Python parity mirror).

Byte-identical decisions with `packages/contracts/authz/check_permission.ts`
function `checkPermissionDecide`. TS is the reference; parity is enforced
by `tests/contract/authz-parity.test.ts` across eight fixture inputs.

Fixture-based parity (no DB). The fixture declares the pre-resolved
state (role, role_permissions, user_grants) and the permission to check;
both implementations must agree on the resulting (allowed, reason).

Decision-order contract (must match TS char-for-char):

    1. If `permission` is not in `known_permissions` (when provided),
       return `unknown_permission` — fail closed.
    2. If `role` is None (no active membership), return `no_membership`
       even when an `allow` user grant exists. Per Loop 4 Phase 1,
       permission_grants ride on top of a role; they do not synthesize
       one.
    3. Start from the role default: allowed if `role_permissions`
       contains the key, reason `role_default`; else
       `role_lacks_permission`.
    4. Apply `allow` overrides: bump `allowed=True`, reason
       `allow_override`.
    5. Apply `deny` overrides last (they win over everything above),
       reason `deny_override`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Optional

GrantType = Literal["allow", "deny"]
DecisionReason = Literal[
    "role_default",
    "allow_override",
    "deny_override",
    "no_membership",
    "role_lacks_permission",
    "unknown_permission",
]


@dataclass(frozen=True)
class UserGrant:
    permission_key: str
    grant_type: GrantType


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: DecisionReason
    role: Optional[str]

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "role": self.role,
        }


def check_permission_decide(
    *,
    role: Optional[str],
    role_permissions: Iterable[str],
    user_grants: Iterable[UserGrant],
    permission: str,
    known_permissions: Optional[Iterable[str]] = None,
) -> PermissionDecision:
    if known_permissions is not None:
        known_set = set(known_permissions)
        if permission not in known_set:
            return PermissionDecision(
                allowed=False, reason="unknown_permission", role=role
            )

    if role is None:
        return PermissionDecision(allowed=False, reason="no_membership", role=None)

    role_perms_list = list(role_permissions)
    grants_list = list(user_grants)

    in_role = permission in role_perms_list
    allowed = in_role
    reason: DecisionReason = "role_default" if in_role else "role_lacks_permission"

    for g in grants_list:
        if g.permission_key == permission and g.grant_type == "allow":
            allowed = True
            reason = "allow_override"
    for g in grants_list:
        if g.permission_key == permission and g.grant_type == "deny":
            allowed = False
            reason = "deny_override"

    return PermissionDecision(allowed=allowed, reason=reason, role=role)
