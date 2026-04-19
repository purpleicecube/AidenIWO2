import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const OPERATOR_KLEAR = "operator_klear@dev.local";
const OPERATOR_FFAI = "operator_ffai@dev.local";
const SUPER = "super@dev.local";
const INTRUDER = "intruder@dev.local";

const LIST_WORKFLOWS_FOR_USER = `
  SELECT wf.key, wf.display_name, c.designation
  FROM workflows wf
  JOIN clients c ON c.id = wf.client_id
  JOIN client_memberships m ON m.client_id = wf.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, wf.key
`;

// Workflow templates are tenant-scoped transitively through their workflow.
const LIST_TEMPLATES_FOR_USER = `
  SELECT wt.id, wt.version, wf.key AS workflow_key, c.designation
  FROM workflow_templates wt
  JOIN workflows wf ON wf.id = wt.workflow_id
  JOIN clients c ON c.id = wf.client_id
  JOIN client_memberships m ON m.client_id = wf.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, wf.key, wt.version
`;

describeIwo3("Loop 3 Phase 1 — tenant workflow isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  it("Klear Operator sees only the Klear workflow", async () => {
    const { rows } = await pool.query<{ key: string }>(LIST_WORKFLOWS_FOR_USER, [
      OPERATOR_KLEAR,
    ]);
    expect(rows.map((r) => r.key)).toEqual(["weekly_marketing_brief"]);
  });

  it("FFAI Operator sees only the FFAI workflow", async () => {
    const { rows } = await pool.query<{ key: string }>(LIST_WORKFLOWS_FOR_USER, [
      OPERATOR_FFAI,
    ]);
    expect(rows.map((r) => r.key)).toEqual(["bench_report_v1"]);
  });

  it("super (owner on both) sees both workflows", async () => {
    const { rows } = await pool.query<{ key: string }>(LIST_WORKFLOWS_FOR_USER, [
      SUPER,
    ]);
    expect(rows.map((r) => r.key).sort()).toEqual([
      "bench_report_v1",
      "weekly_marketing_brief",
    ]);
  });

  it("intruder sees zero workflows", async () => {
    const { rows } = await pool.query(LIST_WORKFLOWS_FOR_USER, [INTRUDER]);
    expect(rows).toHaveLength(0);
  });

  it("Klear Operator sees only Klear workflow templates (tenant scope is transitive)", async () => {
    const { rows } = await pool.query<{
      workflow_key: string;
      version: string;
      designation: string;
    }>(LIST_TEMPLATES_FOR_USER, [OPERATOR_KLEAR]);
    expect(rows).toHaveLength(1);
    expect(rows[0].workflow_key).toBe("weekly_marketing_brief");
    expect(rows[0].version).toBe("1");
    expect(rows[0].designation).toBe("IWO | Klear.ai");
  });

  it("intruder sees zero workflow templates", async () => {
    const { rows } = await pool.query(LIST_TEMPLATES_FOR_USER, [INTRUDER]);
    expect(rows).toHaveLength(0);
  });
});
