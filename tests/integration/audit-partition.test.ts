import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

import { AUDIT_EVENTS } from "../../packages/contracts/audit/events";
import { writeAuditRow } from "../../packages/contracts/audit/writer";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001";
const KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002";

describeIwo3("ADR-010 Phase 1.5 — action_audit_log monthly partitioning", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    // Clean only partition-test rows.
    await pool.query(
      `DELETE FROM action_audit_log
       WHERE metadata->>'test_marker' = 'audit-partition'`
    );
    await pool.end();
  });

  it("`action_audit_log` is a partitioned table keyed on created_at", async () => {
    const { rows } = await pool.query<{ partstrat: string; partkey: string }>(
      `SELECT pt.partstrat, pg_get_expr(pt.partexprs, pt.partrelid) AS partexprs,
              array_to_string(pt.partattrs::int[], ',') AS partattrs
       FROM pg_partitioned_table pt
       JOIN pg_class c ON c.oid = pt.partrelid
       JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'public' AND c.relname = 'action_audit_log'`
    );
    expect(rows, "action_audit_log must be partitioned").toHaveLength(1);
    expect(rows[0].partstrat).toBe("r"); // 'r' = RANGE

    // Confirm the partition key is `created_at`.
    const { rows: cols } = await pool.query<{ attname: string }>(
      `SELECT a.attname
       FROM pg_partitioned_table pt
       JOIN pg_attribute a
         ON a.attrelid = pt.partrelid
        AND a.attnum = ANY(pt.partattrs::int[])
       JOIN pg_class c ON c.oid = pt.partrelid
       WHERE c.relname = 'action_audit_log'`
    );
    expect(cols.map((c) => c.attname)).toEqual(["created_at"]);
  });

  it("at least three monthly partitions exist (2026-04 through 2026-06)", async () => {
    const { rows } = await pool.query<{ relname: string }>(
      `SELECT c.relname
       FROM pg_inherits i
       JOIN pg_class c ON c.oid = i.inhrelid
       JOIN pg_class p ON p.oid = i.inhparent
       WHERE p.relname = 'action_audit_log'
       ORDER BY c.relname`
    );
    const names = rows.map((r) => r.relname);
    for (const expected of [
      "action_audit_log_y2026m04",
      "action_audit_log_y2026m05",
      "action_audit_log_y2026m06",
    ]) {
      expect(names, `expected partition ${expected}`).toContain(expected);
    }
  });

  it("rows route to the correct monthly partition by created_at", async () => {
    const c = await pool.connect();
    try {
      await c.query("BEGIN");
      // Insert three rows whose created_at values land in different
      // partitions. The writer insert itself uses now(), so we override via
      // an explicit INSERT to exercise routing.
      const samples = [
        {
          ts: "2026-04-15T12:00:00Z",
          partition: "action_audit_log_y2026m04",
        },
        {
          ts: "2026-05-15T12:00:00Z",
          partition: "action_audit_log_y2026m05",
        },
        {
          ts: "2026-06-15T12:00:00Z",
          partition: "action_audit_log_y2026m06",
        },
      ];
      for (const s of samples) {
        await c.query(
          `INSERT INTO action_audit_log
             (client_id, actor_user_id, action, target_type, target_id, metadata, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7)`,
          [
            KLEAR_CLIENT,
            KLEAR_ADMIN,
            AUDIT_EVENTS.ARTIFACT_UPLOADED,
            "artifact",
            `partition-test-${s.ts}`,
            JSON.stringify({
              test_marker: "audit-partition",
              expected_partition: s.partition,
            }),
            s.ts,
          ]
        );
      }
      await c.query("COMMIT");
    } finally {
      c.release();
    }

    for (const part of [
      "action_audit_log_y2026m04",
      "action_audit_log_y2026m05",
      "action_audit_log_y2026m06",
    ]) {
      const { rows } = await pool.query<{ count: string }>(
        `SELECT count(*)::text AS count
         FROM ONLY ${part}
         WHERE metadata->>'test_marker' = 'audit-partition'`
      );
      expect(Number(rows[0].count), `${part} should hold one row`).toBe(1);
    }
  });

  it("ensure_audit_partition_for() creates a missing partition, idempotent on reruns", async () => {
    // Use a far-future month that is NOT pre-seeded.
    const ts = "2030-01-15T12:00:00Z";
    const partName = "action_audit_log_y2030m01";

    // Ensure it doesn't exist at the start (clean any residual from prior
    // test runs).
    await pool.query(`DROP TABLE IF EXISTS ${partName}`);

    await pool.query(`SELECT ensure_audit_partition_for($1::timestamptz)`, [ts]);

    const { rows: firstCheck } = await pool.query<{ relname: string }>(
      `SELECT c.relname
       FROM pg_class c
       JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'public' AND c.relname = $1`,
      [partName]
    );
    expect(firstCheck).toHaveLength(1);

    // Idempotent: a second call is a no-op.
    await pool.query(`SELECT ensure_audit_partition_for($1::timestamptz)`, [ts]);
    const { rows: secondCheck } = await pool.query<{ relname: string }>(
      `SELECT c.relname
       FROM pg_class c
       JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'public' AND c.relname = $1`,
      [partName]
    );
    expect(secondCheck).toHaveLength(1);

    // Writer then works into the just-created partition.
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        `INSERT INTO action_audit_log
           (client_id, actor_user_id, action, target_type, target_id, metadata, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7)`,
        [
          KLEAR_CLIENT,
          KLEAR_ADMIN,
          AUDIT_EVENTS.ARTIFACT_UPLOADED,
          "artifact",
          "future-partition-test",
          JSON.stringify({ test_marker: "audit-partition", scenario: "future" }),
          ts,
        ]
      );
      await client.query("COMMIT");
    } finally {
      client.release();
    }

    const { rows: count } = await pool.query<{ count: string }>(
      `SELECT count(*)::text AS count
       FROM ONLY ${partName}
       WHERE metadata->>'test_marker' = 'audit-partition'`
    );
    expect(Number(count[0].count)).toBe(1);

    // Cleanup: drop the 2030 partition so subsequent test runs start fresh.
    await pool.query(`DROP TABLE IF EXISTS ${partName}`);
  });

  it("writer helper still works against the partitioned table", async () => {
    const c = await pool.connect();
    try {
      await c.query("BEGIN");
      const { id } = await writeAuditRow(c, {
        clientId: KLEAR_CLIENT,
        actorUserId: KLEAR_ADMIN,
        event: AUDIT_EVENTS.PROMPT_PROFILE_CREATED,
        targetType: "prompt_profile",
        targetId: "partition-writer-test",
        metadata: { test_marker: "audit-partition", via: "writer" },
      });
      await c.query("COMMIT");

      const { rows } = await pool.query<{ client_id: string; action: string }>(
        `SELECT client_id, action FROM action_audit_log WHERE id = $1`,
        [id]
      );
      expect(rows).toHaveLength(1);
      expect(rows[0].client_id).toBe(KLEAR_CLIENT);
      expect(rows[0].action).toBe("prompt_profile.created");
    } finally {
      c.release();
    }
  });
});
