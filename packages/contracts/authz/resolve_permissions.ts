/**
 * Loop 4 Phase 1 — resolve the permission keys a user holds in a given
 * (user, client) context.
 *
 * This is the read-side of the RBAC model. Phase 4.2 wraps it in the
 * public `checkPermission(client, { userId, clientId, permission })`
 * helper that returns `{ allowed, reason }` and in the throwing
 * `requirePermission(...)` with audit writing.
 *
 * Resolution order (deny wins):
 *   1. Lookup active client_memberships row on (user_id, client_id).
 *      None found → empty set (intruder / cross-tenant / revoked).
 *   2. Load role_permissions for that role → starting set.
 *   3. Overlay permission_grants for (user_id, client_id):
 *        grant_type = allow → add to set
 *        grant_type = deny  → remove from set (applied after allow so
 *                              an explicit deny overrides an explicit allow
 *                              and the role default).
 *   4. Return the final set of permission_key strings.
 *
 * The resolver does NOT consult the six-role enum directly — it reads
 * the membership row, so a later migration that adds a seventh role is
 * purely a data change (add role_permissions rows). The caller passes a
 * `pg` Pool/PoolClient; we never open our own connection.
 */

import type { Pool, PoolClient } from "pg";

type Runner = Pool | PoolClient;

export interface ResolvePermissionsInput {
  userId: string;
  clientId: string;
}

export interface ResolvePermissionsResult {
  /** The active role on this tenant, or null if no active membership. */
  role: string | null;
  /** Full set of permission keys the user holds in this tenant. */
  permissions: Set<string>;
}

export async function resolveUserPermissions(
  db: Runner,
  input: ResolvePermissionsInput
): Promise<ResolvePermissionsResult> {
  const mem = await db.query<{ role: string }>(
    `SELECT role
     FROM client_memberships
     WHERE user_id = $1 AND client_id = $2 AND status = 'active'
     LIMIT 1`,
    [input.userId, input.clientId]
  );
  if (mem.rows.length === 0) {
    return { role: null, permissions: new Set<string>() };
  }

  const role = mem.rows[0].role;

  const rolePerms = await db.query<{ permission_key: string }>(
    `SELECT p.permission_key
     FROM role_permissions rp
     JOIN permissions p ON p.id = rp.permission_id
     WHERE rp.role = $1`,
    [role]
  );
  const set = new Set<string>(rolePerms.rows.map((r) => r.permission_key));

  const overrides = await db.query<{
    permission_key: string;
    grant_type: "allow" | "deny";
  }>(
    `SELECT p.permission_key, pg.grant_type
     FROM permission_grants pg
     JOIN permissions p ON p.id = pg.permission_id
     WHERE pg.user_id = $1 AND pg.client_id = $2`,
    [input.userId, input.clientId]
  );

  // Apply allow first, then deny — deny wins when both exist on the same
  // (user, client, permission) triple (the unique index prevents that
  // literal case, but an allow override on top of a role default + a
  // deny override in the DB is the pathological case we want safe).
  for (const r of overrides.rows) {
    if (r.grant_type === "allow") set.add(r.permission_key);
  }
  for (const r of overrides.rows) {
    if (r.grant_type === "deny") set.delete(r.permission_key);
  }

  return { role, permissions: set };
}
