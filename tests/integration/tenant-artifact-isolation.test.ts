import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const OPERATOR_KLEAR = "operator_klear@dev.local";
const OPERATOR_FFAI = "operator_ffai@dev.local";
const INTRUDER = "intruder@dev.local";

// Service-layer tenant filter: the artifact's client must match a client
// the user holds an active membership on.
const LIST_ARTIFACTS_FOR_USER = `
  SELECT a.filename, c.designation
  FROM artifacts a
  JOIN clients c ON c.id = a.client_id
  JOIN client_memberships m ON m.client_id = a.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, a.filename
`;

const READ_SPECIFIC_ARTIFACT_FOR_USER = `
  SELECT a.id
  FROM artifacts a
  JOIN client_memberships m ON m.client_id = a.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1 AND a.id = $2
`;

// Klear onepager + rmis summary, FFAI mission + bench run
const KLEAR_ARTIFACT_ID = "00000000-0000-4000-8000-000050000001";
const FFAI_ARTIFACT_ID = "00000000-0000-4000-8000-000050000003";

describeIwo3("Loop 2 Phase 2 — tenant artifact isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  it("Klear Operator sees only Klear artifacts", async () => {
    const { rows } = await pool.query<{ filename: string; designation: string }>(
      LIST_ARTIFACTS_FOR_USER,
      [OPERATOR_KLEAR]
    );
    expect(rows.map((r) => r.filename).sort()).toEqual([
      "klear_onepager.md",
      "klear_rmis_summary.txt",
    ]);
    for (const r of rows) expect(r.designation).toBe("IWO | Klear.ai");
  });

  it("FFAI Operator sees only FFAI artifacts", async () => {
    const { rows } = await pool.query<{ filename: string; designation: string }>(
      LIST_ARTIFACTS_FOR_USER,
      [OPERATOR_FFAI]
    );
    expect(rows.map((r) => r.filename).sort()).toEqual([
      "ffai_bench_run_2026_04.json",
      "ffai_mission.md",
    ]);
    for (const r of rows) expect(r.designation).toBe("IWO | FreedomForge.AI");
  });

  it("FFAI user cannot read a Klear artifact by id", async () => {
    const { rows } = await pool.query(READ_SPECIFIC_ARTIFACT_FOR_USER, [
      OPERATOR_FFAI,
      KLEAR_ARTIFACT_ID,
    ]);
    expect(rows).toHaveLength(0);
  });

  it("Klear user cannot read an FFAI artifact by id", async () => {
    const { rows } = await pool.query(READ_SPECIFIC_ARTIFACT_FOR_USER, [
      OPERATOR_KLEAR,
      FFAI_ARTIFACT_ID,
    ]);
    expect(rows).toHaveLength(0);
  });

  it("intruder sees zero artifacts", async () => {
    const { rows } = await pool.query(LIST_ARTIFACTS_FOR_USER, [INTRUDER]);
    expect(rows).toHaveLength(0);
  });
});
