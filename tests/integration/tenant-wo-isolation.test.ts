import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const OPERATOR_KLEAR = "operator_klear@dev.local";
const OPERATOR_FFAI = "operator_ffai@dev.local";
const SUPER = "super@dev.local";
const INTRUDER = "intruder@dev.local";

// Canonical service-layer tenant filter pattern for work_orders.
// Every Loop 3+ handler must use this JOIN shape. A02 + A07 + D01 in the
// risk register all reference this invariant.
const LIST_WO_FOR_USER = `
  SELECT wo.id, wo.title, wo.status, c.designation
  FROM work_orders wo
  JOIN clients c ON c.id = wo.client_id
  JOIN client_memberships m ON m.client_id = wo.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, wo.created_at
`;

const READ_SPECIFIC_WO_FOR_USER = `
  SELECT wo.id
  FROM work_orders wo
  JOIN client_memberships m ON m.client_id = wo.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1 AND wo.id = $2
`;

const KLEAR_WO_ID = "00000000-0000-4000-8000-000060000001";
const FFAI_WO_ID = "00000000-0000-4000-8000-000060000002";

describeIwo3("Loop 3 Phase 1 — tenant work-order isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  it("Klear Operator sees only Klear work orders", async () => {
    const { rows } = await pool.query<{
      title: string;
      designation: string;
    }>(LIST_WO_FOR_USER, [OPERATOR_KLEAR]);
    expect(rows).toHaveLength(1);
    expect(rows[0].title).toMatch(/RMIS/);
    expect(rows[0].designation).toBe("IWO | Klear.ai");
  });

  it("FFAI Operator sees only FFAI work orders", async () => {
    const { rows } = await pool.query<{
      title: string;
      designation: string;
    }>(LIST_WO_FOR_USER, [OPERATOR_FFAI]);
    expect(rows).toHaveLength(1);
    expect(rows[0].title).toMatch(/Benchmark/);
    expect(rows[0].designation).toBe("IWO | FreedomForge.AI");
  });

  it("FFAI Operator cannot read a Klear WO by id (tenant isolation)", async () => {
    const { rows } = await pool.query(READ_SPECIFIC_WO_FOR_USER, [
      OPERATOR_FFAI,
      KLEAR_WO_ID,
    ]);
    expect(rows).toHaveLength(0);
  });

  it("Klear Operator cannot read an FFAI WO by id", async () => {
    const { rows } = await pool.query(READ_SPECIFIC_WO_FOR_USER, [
      OPERATOR_KLEAR,
      FFAI_WO_ID,
    ]);
    expect(rows).toHaveLength(0);
  });

  it("super (owner on both) sees both tenant WOs", async () => {
    const { rows } = await pool.query<{ designation: string }>(
      LIST_WO_FOR_USER,
      [SUPER]
    );
    expect(rows.map((r) => r.designation).sort()).toEqual([
      "IWO | FreedomForge.AI",
      "IWO | Klear.ai",
    ]);
  });

  it("intruder (no memberships) sees zero WOs", async () => {
    const { rows } = await pool.query(LIST_WO_FOR_USER, [INTRUDER]);
    expect(rows).toHaveLength(0);
  });
});
