/**
 * Loop 4 Phase 2 — authorization helper.
 *
 * Two public entry points:
 *
 *   checkPermissionDecide(input)          — pure decision function. No DB.
 *                                           Shared byte-identically with
 *                                           Python at
 *                                           apps/api-fastapi/authz/
 *                                           check_permission.py. Fixture
 *                                           parity is enforced by
 *                                           tests/contract/authz-parity.test.ts.
 *
 *   checkPermission(db, { userId,         — DB-bound convenience wrapper.
 *                         clientId,         Loads the membership row,
 *                         permission })     role_permissions for the role,
 *                                           and permission_grants overlay,
 *                                           then hands off to the pure
 *                                           decision function.
 *
 * The throwing wrapper + audit-writing variant `requirePermission` lives
 * in `require_permission.ts`. The adapter-registry dispatcher imports
 * `requirePermission` — not `checkPermission` — so every denied dispatch
 * automatically emits an `authz.denied` audit row.
 *
 * Decision-order contract (must match Python char-for-char):
 *
 *   1. If `permission` is not in the caller-provided `knownPermissions`
 *      set (or the caller opts out of vocabulary guarding), return
 *      `unknown_permission` — fail closed.
 *   2. If `role` is null (no active membership), return `no_membership`
 *      even if a per-user `allow` grant exists. Per Loop 4 Phase 1
 *      contract, a permission_grant rides on top of a role, it does not
 *      synthesize one.
 *   3. Start from the role default: allowed if `rolePermissions` contains
 *      the key, reason `role_default`; else `role_lacks_permission`.
 *   4. Apply `allow` overrides: bump `allowed=true`, reason
 *      `allow_override`.
 *   5. Apply `deny` overrides last: they win over everything above,
 *      reason `deny_override`.
 */

import type { Pool, PoolClient } from "pg";
import { resolveUserPermissions } from "./resolve_permissions";

type Runner = Pool | PoolClient;

export type PermissionDecisionReason =
  | "role_default"
  | "allow_override"
  | "deny_override"
  | "no_membership"
  | "role_lacks_permission"
  | "unknown_permission";

export interface PermissionDecision {
  allowed: boolean;
  reason: PermissionDecisionReason;
  role: string | null;
}

export interface PureDecideInput {
  role: string | null;
  rolePermissions: readonly string[];
  userGrants: readonly {
    permissionKey: string;
    grantType: "allow" | "deny";
  }[];
  permission: string;
  /**
   * Optional vocabulary guard. When provided, any `permission` not in the
   * set returns `unknown_permission`. Callers coming through the DB path
   * always provide this from the `permissions` table.
   */
  knownPermissions?: ReadonlySet<string>;
}

export function checkPermissionDecide(
  input: PureDecideInput
): PermissionDecision {
  if (input.knownPermissions && !input.knownPermissions.has(input.permission)) {
    return {
      allowed: false,
      reason: "unknown_permission",
      role: input.role,
    };
  }

  if (input.role === null) {
    return { allowed: false, reason: "no_membership", role: null };
  }

  const inRole = input.rolePermissions.includes(input.permission);
  let allowed = inRole;
  let reason: PermissionDecisionReason = inRole
    ? "role_default"
    : "role_lacks_permission";

  // Allow overrides first
  for (const g of input.userGrants) {
    if (g.permissionKey === input.permission && g.grantType === "allow") {
      allowed = true;
      reason = "allow_override";
    }
  }
  // Deny overrides last (win)
  for (const g of input.userGrants) {
    if (g.permissionKey === input.permission && g.grantType === "deny") {
      allowed = false;
      reason = "deny_override";
    }
  }

  return { allowed, reason, role: input.role };
}

export interface CheckPermissionInput {
  userId: string;
  clientId: string;
  permission: string;
}

/**
 * DB-bound permission check. Loads the role, the role's grant set, and
 * any per-user overrides, then hands off to `checkPermissionDecide`.
 *
 * Performs a vocabulary guard against the `permissions` table so an
 * unknown key (typo, unlisted permission) fails closed with
 * `unknown_permission`. Phase 4.4 adds an eslint rule that catches this
 * at lint time, too.
 */
export async function checkPermission(
  db: Runner,
  input: CheckPermissionInput
): Promise<PermissionDecision> {
  const vocab = await db.query<{ permission_key: string }>(
    `SELECT permission_key FROM permissions`
  );
  const knownPermissions = new Set(vocab.rows.map((r) => r.permission_key));
  if (!knownPermissions.has(input.permission)) {
    return { allowed: false, reason: "unknown_permission", role: null };
  }

  const resolved = await resolveUserPermissions(db, {
    userId: input.userId,
    clientId: input.clientId,
  });

  if (resolved.role === null) {
    return { allowed: false, reason: "no_membership", role: null };
  }

  // Rebuild the inputs for the pure function so the DB path and the
  // parity path share the same decision tree. We already have the
  // resolved set, but for reason fidelity we need the pre-overlay state
  // + the grants list. Re-query grants + role_permissions cheap-ish;
  // Loop 5+ may cache this.
  const rolePerms = await db.query<{ permission_key: string }>(
    `SELECT p.permission_key
     FROM role_permissions rp
     JOIN permissions p ON p.id = rp.permission_id
     WHERE rp.role = $1`,
    [resolved.role]
  );
  const grants = await db.query<{
    permission_key: string;
    grant_type: "allow" | "deny";
  }>(
    `SELECT p.permission_key, pg.grant_type
     FROM permission_grants pg
     JOIN permissions p ON p.id = pg.permission_id
     WHERE pg.user_id = $1 AND pg.client_id = $2`,
    [input.userId, input.clientId]
  );

  return checkPermissionDecide({
    role: resolved.role,
    rolePermissions: rolePerms.rows.map((r) => r.permission_key),
    userGrants: grants.rows.map((r) => ({
      permissionKey: r.permission_key,
      grantType: r.grant_type,
    })),
    permission: input.permission,
    knownPermissions,
  });
}
