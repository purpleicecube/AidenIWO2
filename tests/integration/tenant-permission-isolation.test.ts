import { describe, it, expect, afterAll, beforeEach } from "vitest";
import { Pool } from "pg";

import { checkPermission } from "../../packages/contracts/authz/check_permission";
import {
  PermissionDenied,
  requirePermission,
} from "../../packages/contracts/authz/require_permission";
import { AUDIT_EVENTS } from "../../packages/contracts/audit/events";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR = "00000000-0000-4000-8000-00000000c001";
const FFAI = "00000000-0000-4000-8000-00000000c002";

const KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002";
const KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003";
const FFAI_ADMIN = "00000000-0000-4000-8000-000002000002";
const SUPER = "00000000-0000-4000-8000-000099000001";
const INTRUDER = "00000000-0000-4000-8000-000099000002";

describeIwo3("Loop 4 Phase 2 — tenant-scoped permission isolation", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    // Clear any authz.denied audit rows left from prior runs. Scope by
    // test marker to avoid touching other audit tests' rows.
    await pool.query(
      `DELETE FROM action_audit_log
       WHERE action = 'authz.denied'
         AND metadata->>'test_marker' = 'tenant-permission-isolation'`
    );
  });

  it("Klear admin has admin grants on Klear — but not on FFAI", async () => {
    const onKlear = await checkPermission(pool, {
      userId: KLEAR_ADMIN,
      clientId: KLEAR,
      permission: "user:invite",
    });
    const onFfai = await checkPermission(pool, {
      userId: KLEAR_ADMIN,
      clientId: FFAI,
      permission: "user:invite",
    });
    expect(onKlear.allowed).toBe(true);
    expect(onKlear.role).toBe("admin");
    expect(onFfai.allowed).toBe(false);
    expect(onFfai.role).toBeNull();
    expect(onFfai.reason).toBe("no_membership");
  });

  it("super user has owner grants on both tenants", async () => {
    const onKlear = await checkPermission(pool, {
      userId: SUPER,
      clientId: KLEAR,
      permission: "system:admin",
    });
    const onFfai = await checkPermission(pool, {
      userId: SUPER,
      clientId: FFAI,
      permission: "system:admin",
    });
    expect(onKlear.allowed).toBe(true);
    expect(onFfai.allowed).toBe(true);
    expect(onKlear.role).toBe("owner");
    expect(onFfai.role).toBe("owner");
  });

  it("intruder is denied on every tenant, every permission", async () => {
    for (const clientId of [KLEAR, FFAI]) {
      for (const perm of [
        "work_order:read",
        "output_package:submit",
        "system:admin",
      ]) {
        const d = await checkPermission(pool, {
          userId: INTRUDER,
          clientId,
          permission: perm,
        });
        expect(d.allowed, `${perm} on ${clientId}`).toBe(false);
        expect(d.role).toBeNull();
      }
    }
  });

  it("requirePermission writes authz.denied + throws PermissionDenied on deny", async () => {
    const client = await pool.connect();
    let caught: unknown = null;
    try {
      await client.query("BEGIN");
      await requirePermission(client, {
        userId: KLEAR_OPERATOR,
        clientId: KLEAR,
        permission: "output_handoff:approve_send",
        targetType: "output_handoff",
        targetId: "test-handoff-id",
        metadata: { test_marker: "tenant-permission-isolation" },
      });
      await client.query("COMMIT");
    } catch (err) {
      caught = err;
      await client.query("COMMIT"); // audit row still persisted before throw
    } finally {
      client.release();
    }

    expect(caught).toBeInstanceOf(PermissionDenied);
    if (caught instanceof PermissionDenied) {
      expect(caught.permission).toBe("output_handoff:approve_send");
      expect(caught.reason).toBe("role_lacks_permission");
      expect(caught.role).toBe("operator");
    }

    const { rows } = await pool.query<{
      action: string;
      client_id: string;
      actor_user_id: string;
      target_id: string;
      metadata: {
        permission?: string;
        decision_reason?: string;
        role?: string;
      };
    }>(
      `SELECT action, client_id, actor_user_id, target_id, metadata
       FROM action_audit_log
       WHERE metadata->>'test_marker' = 'tenant-permission-isolation'`
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].action).toBe(AUDIT_EVENTS.AUTHZ_DENIED);
    expect(rows[0].client_id).toBe(KLEAR);
    expect(rows[0].actor_user_id).toBe(KLEAR_OPERATOR);
    expect(rows[0].target_id).toBe("test-handoff-id");
    expect(rows[0].metadata.permission).toBe("output_handoff:approve_send");
    expect(rows[0].metadata.decision_reason).toBe("role_lacks_permission");
    expect(rows[0].metadata.role).toBe("operator");
  });

  it("requirePermission is silent on allow (no authz.denied row written)", async () => {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await requirePermission(client, {
        userId: KLEAR_ADMIN,
        clientId: KLEAR,
        permission: "user:invite",
        targetType: "membership",
        targetId: "new-user-invite-id",
        metadata: { test_marker: "tenant-permission-isolation" },
      });
      await client.query("COMMIT");
    } finally {
      client.release();
    }

    const { rows } = await pool.query(
      `SELECT id FROM action_audit_log
       WHERE action = 'authz.denied'
         AND metadata->>'test_marker' = 'tenant-permission-isolation'`
    );
    expect(rows).toHaveLength(0);
  });

  it("FFAI admin denied on a Klear-tenant resource — no cross-tenant grant leak", async () => {
    const d = await checkPermission(pool, {
      userId: FFAI_ADMIN,
      clientId: KLEAR,
      permission: "user:invite",
    });
    expect(d.allowed).toBe(false);
    expect(d.role).toBeNull();
    expect(d.reason).toBe("no_membership");
  });

  it("requirePermission rolls the authz.denied row into the caller's transaction", async () => {
    // If the caller ROLLBACK's their own transaction, the audit row should
    // also roll back (transactional integrity on deny path). This mirrors
    // the Loop 2 `audit-log-invariant.test.ts` behaviour for mutation rows.
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await expect(
        requirePermission(client, {
          userId: KLEAR_OPERATOR,
          clientId: KLEAR,
          permission: "adapter_credential:rotate",
          targetType: "adapter_credential",
          targetId: "some-cred",
          metadata: { test_marker: "tenant-permission-isolation-rollback" },
        })
      ).rejects.toThrow(PermissionDenied);
      await client.query("ROLLBACK");
    } finally {
      client.release();
    }

    const { rows } = await pool.query(
      `SELECT id FROM action_audit_log
       WHERE metadata->>'test_marker' = 'tenant-permission-isolation-rollback'`
    );
    expect(rows).toHaveLength(0);
  });
});
