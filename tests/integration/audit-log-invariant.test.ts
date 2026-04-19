import { describe, it, expect, afterAll, beforeEach } from "vitest";
import { Pool } from "pg";

import { AUDIT_EVENTS, LOOP_2_AUDIT_EVENTS } from "../../packages/contracts/audit/events";
import { writeAuditRow } from "../../packages/contracts/audit/writer";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001";
const FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002";
const KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002";
const FFAI_ADMIN = "00000000-0000-4000-8000-000002000002";

describeIwo3("Loop 2 Phase 2 — audit-log invariant", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    // Clean only the rows we are about to write, identified by a Phase-2
    // test marker in metadata. Keeps the table contents for other tests
    // intact (currently none) and keeps the test idempotent across reruns.
    await pool.query(
      `DELETE FROM action_audit_log WHERE metadata->>'test_marker' = 'audit-log-invariant'`
    );
  });

  it("writer inserts a row with the correct client_id, actor, and event", async () => {
    const c = await pool.connect();
    try {
      await c.query("BEGIN");
      const { id } = await writeAuditRow(c, {
        clientId: KLEAR_CLIENT,
        actorUserId: KLEAR_ADMIN,
        event: AUDIT_EVENTS.PROMPT_PROFILE_CREATED,
        targetType: "prompt_profile",
        targetId: "00000000-0000-4000-8000-000030000001",
        metadata: { test_marker: "audit-log-invariant", note: "single-write" },
      });
      await c.query("COMMIT");

      const { rows } = await pool.query<{
        client_id: string;
        actor_user_id: string | null;
        action: string;
        target_type: string | null;
        target_id: string | null;
      }>(
        `SELECT client_id, actor_user_id, action, target_type, target_id
         FROM action_audit_log WHERE id = $1`,
        [id]
      );
      expect(rows).toHaveLength(1);
      expect(rows[0].client_id).toBe(KLEAR_CLIENT);
      expect(rows[0].actor_user_id).toBe(KLEAR_ADMIN);
      expect(rows[0].action).toBe("prompt_profile.created");
      expect(rows[0].target_type).toBe("prompt_profile");
    } finally {
      c.release();
    }
  });

  it("writer is transactional — rollback drops the audit row", async () => {
    const c = await pool.connect();
    try {
      await c.query("BEGIN");
      await writeAuditRow(c, {
        clientId: KLEAR_CLIENT,
        actorUserId: KLEAR_ADMIN,
        event: AUDIT_EVENTS.REPOSITORY_BINDING_CREATED,
        targetType: "repository_binding",
        targetId: "test-rollback",
        metadata: { test_marker: "audit-log-invariant", note: "will-rollback" },
      });
      await c.query("ROLLBACK");
    } finally {
      c.release();
    }

    const { rows } = await pool.query(
      `SELECT 1 FROM action_audit_log
       WHERE metadata->>'test_marker' = 'audit-log-invariant'
         AND metadata->>'note' = 'will-rollback'`
    );
    expect(rows).toHaveLength(0);
  });

  it("rows are tenant-scoped — Klear-filtered query excludes FFAI writes", async () => {
    const c = await pool.connect();
    try {
      await c.query("BEGIN");
      await writeAuditRow(c, {
        clientId: KLEAR_CLIENT,
        actorUserId: KLEAR_ADMIN,
        event: AUDIT_EVENTS.ARTIFACT_UPLOADED,
        targetType: "artifact",
        targetId: "klear-artifact-test",
        metadata: { test_marker: "audit-log-invariant", tenant: "klear" },
      });
      await writeAuditRow(c, {
        clientId: FFAI_CLIENT,
        actorUserId: FFAI_ADMIN,
        event: AUDIT_EVENTS.ARTIFACT_UPLOADED,
        targetType: "artifact",
        targetId: "ffai-artifact-test",
        metadata: { test_marker: "audit-log-invariant", tenant: "ffai" },
      });
      await c.query("COMMIT");
    } finally {
      c.release();
    }

    const { rows: klearRows } = await pool.query(
      `SELECT metadata->>'tenant' AS tenant
       FROM action_audit_log
       WHERE client_id = $1
         AND metadata->>'test_marker' = 'audit-log-invariant'`,
      [KLEAR_CLIENT]
    );
    const { rows: ffaiRows } = await pool.query(
      `SELECT metadata->>'tenant' AS tenant
       FROM action_audit_log
       WHERE client_id = $1
         AND metadata->>'test_marker' = 'audit-log-invariant'`,
      [FFAI_CLIENT]
    );
    expect(klearRows.map((r) => r.tenant)).toEqual(["klear"]);
    expect(ffaiRows.map((r) => r.tenant)).toEqual(["ffai"]);
  });

  it("all Loop-2 event vocabulary strings are well-formed and registered", () => {
    expect(LOOP_2_AUDIT_EVENTS.length).toBe(12);
    for (const event of LOOP_2_AUDIT_EVENTS) {
      expect(event).toMatch(/^[a-z_]+\.[a-z_]+$/);
    }
    // Spot-check a handful against the object literal.
    expect(Object.values(AUDIT_EVENTS)).toContain("prompt_profile.created");
    expect(Object.values(AUDIT_EVENTS)).toContain("artifact.uploaded");
    expect(Object.values(AUDIT_EVENTS)).toContain(
      "repository_binding.credential_rotated"
    );
  });
});
