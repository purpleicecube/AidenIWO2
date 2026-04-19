import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

/**
 * In Loop 1 no IWO2 operational tables are mirrored yet, so this test
 * passes by absence. As soon as Loop 2+ mirrors one of these tables into
 * IWO3 it must be empty after reset+seed.
 */
const IWO2_OPERATIONAL_TABLES = [
  "work_orders",
  "workflow_executions",
  "workflow_step_runs",
  "chat_sessions",
  "chat_messages",
  "gamma_generation_records",
  "approvals",
  "execution_logs",
  "tool_leases",
  "context_retrievals",
];

describeIwo3("Loop 1 — clean baseline invariant", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("no IWO2-operational table is populated", async () => {
    const { rows } = await pool.query<{ table_name: string }>(
      `SELECT table_name FROM information_schema.tables WHERE table_schema='public'`
    );
    const existing = new Set(rows.map((r) => r.table_name));

    for (const t of IWO2_OPERATIONAL_TABLES) {
      if (!existing.has(t)) continue;
      const { rows: cnt } = await pool.query<{ count: string }>(
        `SELECT count(*)::text as count FROM ${t}`
      );
      expect(Number(cnt[0].count), `${t} should be empty`).toBe(0);
    }
  });
});
