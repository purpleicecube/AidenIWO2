import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

/**
 * Clean-baseline invariant: no IWO2 operational table whose rows were
 * carried forward from the IWO2 runtime should be populated.
 *
 * Loop 3 Phase 1 intentionally created `work_orders`, `workflow_executions`,
 * and `workflow_step_runs` as IWO3-NATIVE tables (tenant-first schema, no
 * IWO2 row mirroring — per ADR-005 + ADR-011). They are populated from
 * Loop 3 seed JSON, NOT from IWO2. They are removed from this list.
 *
 * The remaining tables are IWO2-only and would only appear in IWO3 if
 * someone mirrored them forward; if they ever do appear, they must be
 * empty after reset+seed.
 */
const IWO2_OPERATIONAL_TABLES = [
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
