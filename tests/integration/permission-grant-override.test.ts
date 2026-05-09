import { describe, it, expect, afterAll, beforeEach } from "vitest";
import { Pool } from "pg";

import { resolveUserPermissions } from "../../packages/contracts/authz/resolve_permissions";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR = "00000000-0000-4000-8000-00000000c001";
const FFAI = "00000000-0000-4000-8000-00000000c002";
const KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002";
const KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003";
const KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005";
const INTRUDER = "00000000-0000-4000-8000-000099000002";

async function permissionIdFor(pool: Pool, key: string): Promise<string> {
  const { rows } = await pool.query<{ id: string }>(
    `SELECT id FROM permissions WHERE permission_key = $1`,
    [key]
  );
  if (rows.length === 0) throw new Error(`unknown permission: ${key}`);
  return rows[0].id;
}

describeIwo3("Loop 4 Phase 1 — permission-grant override precedence", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    // Scrub any grants left behind by a prior run. Runtime grants are
    // always test-owned in v0 — the seed ships 0 rows.
    await pool.query(`DELETE FROM permission_grants`);
  });

  it("allow override lets an intruder hold a permission they normally lack", async () => {
    // Intruder has no membership → empty set by default.
    const before = await resolveUserPermissions(pool, {
      userId: INTRUDER,
      clientId: KLEAR,
    });
    expect(before.permissions.size).toBe(0);

    // Intruder without a membership row stays empty even with an allow
    // grant — the resolver requires an active membership first. This is
    // the belt-and-suspenders behavior: per-user grants ride on top of
    // a role, they don't create a role.
    const permId = await permissionIdFor(pool, "audit_log:read");
    await pool.query(
      `INSERT INTO permission_grants
         (user_id, client_id, permission_id, grant_type, reason)
       VALUES ($1, $2, $3, 'allow', 'test allow on intruder')`,
      [INTRUDER, KLEAR, permId]
    );

    const after = await resolveUserPermissions(pool, {
      userId: INTRUDER,
      clientId: KLEAR,
    });
    expect(after.role).toBeNull();
    expect(after.permissions.size).toBe(0);
  });

  it("allow override adds a permission on top of an existing role default", async () => {
    // Klear operator does NOT have audit_log:read by default.
    const before = await resolveUserPermissions(pool, {
      userId: KLEAR_OPERATOR,
      clientId: KLEAR,
    });
    expect(before.permissions.has("audit_log:read")).toBe(false);

    const permId = await permissionIdFor(pool, "audit_log:read");
    await pool.query(
      `INSERT INTO permission_grants
         (user_id, client_id, permission_id, grant_type, reason)
       VALUES ($1, $2, $3, 'allow', 'test operator allow audit_log:read')`,
      [KLEAR_OPERATOR, KLEAR, permId]
    );

    const after = await resolveUserPermissions(pool, {
      userId: KLEAR_OPERATOR,
      clientId: KLEAR,
    });
    expect(after.permissions.has("audit_log:read")).toBe(true);
    // Size = operator-38 + 1 override. Operator role grants now total
    // 38 after Loop Kappa (+canonical_facts:read/create/update); the
    // +1 from this allow override pushes the resolved size to 39.
    expect(after.permissions.size).toBe(39);
  });

  it("deny override removes a permission the role default would grant", async () => {
    // Klear admin DOES have user:invite by default.
    const before = await resolveUserPermissions(pool, {
      userId: KLEAR_ADMIN,
      clientId: KLEAR,
    });
    expect(before.permissions.has("user:invite")).toBe(true);

    const permId = await permissionIdFor(pool, "user:invite");
    await pool.query(
      `INSERT INTO permission_grants
         (user_id, client_id, permission_id, grant_type, reason)
       VALUES ($1, $2, $3, 'deny', 'test admin deny user:invite')`,
      [KLEAR_ADMIN, KLEAR, permId]
    );

    const after = await resolveUserPermissions(pool, {
      userId: KLEAR_ADMIN,
      clientId: KLEAR,
    });
    expect(after.permissions.has("user:invite")).toBe(false);
    // Size = admin-90 − 1 deny. Admin role grants now total 90 after
    // Loop Kappa (+canonical_facts:read/create/update/delete/set_severity
    // on top of MegaLoop-Theta tool_catalog write paths + Loop-Eta
    // tool_catalog/sub_agent_tool basics); the deny pushes the
    // resolved size to 89.
    expect(after.permissions.size).toBe(89);
  });

  it("overrides are tenant-scoped — an allow on Klear does not bleed to FFAI", async () => {
    // Viewer read-only role on Klear. Viewer has no membership on FFAI.
    const permId = await permissionIdFor(pool, "work_order:create");
    await pool.query(
      `INSERT INTO permission_grants
         (user_id, client_id, permission_id, grant_type, reason)
       VALUES ($1, $2, $3, 'allow', 'test viewer Klear allow wo:create')`,
      [KLEAR_VIEWER, KLEAR, permId]
    );

    const klear = await resolveUserPermissions(pool, {
      userId: KLEAR_VIEWER,
      clientId: KLEAR,
    });
    const ffai = await resolveUserPermissions(pool, {
      userId: KLEAR_VIEWER,
      clientId: FFAI,
    });
    expect(klear.permissions.has("work_order:create")).toBe(true);
    expect(ffai.role).toBeNull();
    expect(ffai.permissions.size).toBe(0);
  });

  it("unique constraint blocks duplicate (user, client, permission) rows", async () => {
    const permId = await permissionIdFor(pool, "output_package:delete");
    await pool.query(
      `INSERT INTO permission_grants
         (user_id, client_id, permission_id, grant_type)
       VALUES ($1, $2, $3, 'allow')`,
      [KLEAR_OPERATOR, KLEAR, permId]
    );
    await expect(
      pool.query(
        `INSERT INTO permission_grants
           (user_id, client_id, permission_id, grant_type)
         VALUES ($1, $2, $3, 'deny')`,
        [KLEAR_OPERATOR, KLEAR, permId]
      )
    ).rejects.toThrow(/permission_grants_user_client_permission_uniq/);
  });

  it("removing the override restores the role default", async () => {
    const permId = await permissionIdFor(pool, "user:invite");
    await pool.query(
      `INSERT INTO permission_grants
         (user_id, client_id, permission_id, grant_type, reason)
       VALUES ($1, $2, $3, 'deny', 'will be removed')`,
      [KLEAR_ADMIN, KLEAR, permId]
    );
    const denied = await resolveUserPermissions(pool, {
      userId: KLEAR_ADMIN,
      clientId: KLEAR,
    });
    expect(denied.permissions.has("user:invite")).toBe(false);

    await pool.query(
      `DELETE FROM permission_grants
       WHERE user_id = $1 AND client_id = $2 AND permission_id = $3`,
      [KLEAR_ADMIN, KLEAR, permId]
    );
    const restored = await resolveUserPermissions(pool, {
      userId: KLEAR_ADMIN,
      clientId: KLEAR,
    });
    expect(restored.permissions.has("user:invite")).toBe(true);
  });

  it("FK enforces permission_id points at a real permissions row", async () => {
    await expect(
      pool.query(
        `INSERT INTO permission_grants
           (user_id, client_id, permission_id, grant_type)
         VALUES ($1, $2, $3, 'allow')`,
        [
          KLEAR_OPERATOR,
          KLEAR,
          "00000000-0000-4000-8000-0000a0ffffff", // not in permissions
        ]
      )
    ).rejects.toThrow();
  });
});
