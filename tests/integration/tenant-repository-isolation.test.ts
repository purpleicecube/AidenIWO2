import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const OPERATOR_KLEAR = "operator_klear@dev.local";
const OPERATOR_FFAI = "operator_ffai@dev.local";
const INTRUDER = "intruder@dev.local";
const SUPER = "super@dev.local";

const LIST_REPOSITORY_BINDINGS_FOR_USER = `
  SELECT rb.binding_key, rb.connector_type, c.designation
  FROM repository_bindings rb
  JOIN clients c ON c.id = rb.client_id
  JOIN client_memberships m ON m.client_id = rb.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, rb.binding_key
`;

const LIST_DATA_SOURCE_BINDINGS_FOR_USER = `
  SELECT dsb.binding_key, dsb.connector_type, c.designation
  FROM data_source_bindings dsb
  JOIN clients c ON c.id = dsb.client_id
  JOIN client_memberships m ON m.client_id = dsb.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, dsb.binding_key
`;

describeIwo3("Loop 2 Phase 2 — tenant repository & data-source isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  it("Klear Operator sees only Klear repository bindings", async () => {
    const { rows } = await pool.query<{
      binding_key: string;
      connector_type: string;
    }>(LIST_REPOSITORY_BINDINGS_FOR_USER, [OPERATOR_KLEAR]);
    const keys = rows.map((r) => r.binding_key).sort();
    expect(keys).toEqual(["klear_drive_primary", "klear_local_fixtures"]);
    for (const r of rows) expect(r.connector_type).toMatch(/^(google_drive|local)$/);
  });

  it("FFAI Operator sees only FFAI repository bindings", async () => {
    const { rows } = await pool.query<{ binding_key: string }>(
      LIST_REPOSITORY_BINDINGS_FOR_USER,
      [OPERATOR_FFAI]
    );
    const keys = rows.map((r) => r.binding_key).sort();
    expect(keys).toEqual(["ffai_github_specs", "ffai_local_fixtures"]);
  });

  it("super (owner on both) sees all four repository bindings", async () => {
    const { rows } = await pool.query<{ binding_key: string }>(
      LIST_REPOSITORY_BINDINGS_FOR_USER,
      [SUPER]
    );
    expect(rows.map((r) => r.binding_key).sort()).toEqual([
      "ffai_github_specs",
      "ffai_local_fixtures",
      "klear_drive_primary",
      "klear_local_fixtures",
    ]);
  });

  it("intruder sees zero repository bindings", async () => {
    const { rows } = await pool.query(LIST_REPOSITORY_BINDINGS_FOR_USER, [
      INTRUDER,
    ]);
    expect(rows).toHaveLength(0);
  });

  it("Klear Operator sees only Klear data-source bindings", async () => {
    const { rows } = await pool.query<{
      binding_key: string;
      connector_type: string;
    }>(LIST_DATA_SOURCE_BINDINGS_FOR_USER, [OPERATOR_KLEAR]);
    expect(rows.map((r) => r.binding_key)).toEqual([
      "klear_warehouse_primary",
    ]);
    expect(rows[0].connector_type).toBe("postgres");
  });

  it("FFAI Operator sees only FFAI data-source bindings", async () => {
    const { rows } = await pool.query<{
      binding_key: string;
      connector_type: string;
    }>(LIST_DATA_SOURCE_BINDINGS_FOR_USER, [OPERATOR_FFAI]);
    expect(rows.map((r) => r.binding_key)).toEqual(["ffai_rest_bench_api"]);
    expect(rows[0].connector_type).toBe("rest_api");
  });

  it("intruder sees zero data-source bindings", async () => {
    const { rows } = await pool.query(LIST_DATA_SOURCE_BINDINGS_FOR_USER, [
      INTRUDER,
    ]);
    expect(rows).toHaveLength(0);
  });
});
