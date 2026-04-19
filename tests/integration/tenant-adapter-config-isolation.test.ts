import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const OPERATOR_KLEAR = "operator_klear@dev.local";
const OPERATOR_FFAI = "operator_ffai@dev.local";
const SUPER = "super@dev.local";
const INTRUDER = "intruder@dev.local";

const LIST_CONFIGS_FOR_USER = `
  SELECT ac.adapter_key, ac.category, c.designation
  FROM client_adapter_configs cfg
  JOIN adapter_catalog ac ON ac.id = cfg.adapter_catalog_id
  JOIN clients c ON c.id = cfg.client_id
  JOIN client_memberships m ON m.client_id = cfg.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1 AND cfg.status = 'active'
  ORDER BY c.designation, ac.adapter_key
`;

describeIwo3("Loop 3 Phase 2 — tenant adapter-config isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  it("Klear Operator sees only the three Klear-enabled adapters", async () => {
    const { rows } = await pool.query<{
      adapter_key: string;
      category: string;
    }>(LIST_CONFIGS_FOR_USER, [OPERATOR_KLEAR]);
    expect(rows.map((r) => r.adapter_key).sort()).toEqual([
      "email_campaign",
      "gamma",
      "google_drive",
    ]);
  });

  it("FFAI Operator sees only the two FFAI-enabled adapters", async () => {
    const { rows } = await pool.query<{ adapter_key: string }>(
      LIST_CONFIGS_FOR_USER,
      [OPERATOR_FFAI]
    );
    expect(rows.map((r) => r.adapter_key).sort()).toEqual([
      "gamma",
      "google_drive",
    ]);
  });

  it("super (owner on both) sees all five configs", async () => {
    const { rows } = await pool.query<{
      adapter_key: string;
      designation: string;
    }>(LIST_CONFIGS_FOR_USER, [SUPER]);
    expect(rows).toHaveLength(5);
    const byTenant = new Map<string, string[]>();
    for (const r of rows) {
      if (!byTenant.has(r.designation)) byTenant.set(r.designation, []);
      byTenant.get(r.designation)!.push(r.adapter_key);
    }
    expect(byTenant.get("IWO | Klear.ai")!.sort()).toEqual([
      "email_campaign",
      "gamma",
      "google_drive",
    ]);
    expect(byTenant.get("IWO | FreedomForge.AI")!.sort()).toEqual([
      "gamma",
      "google_drive",
    ]);
  });

  it("intruder sees zero adapter configs", async () => {
    const { rows } = await pool.query(LIST_CONFIGS_FOR_USER, [INTRUDER]);
    expect(rows).toHaveLength(0);
  });

  it("adapter_catalog is tenant-agnostic — all users (even unauthenticated reads) see the same seven kinds", async () => {
    const { rows } = await pool.query<{ adapter_key: string }>(
      `SELECT adapter_key FROM adapter_catalog ORDER BY adapter_key`
    );
    expect(rows.map((r) => r.adapter_key)).toEqual([
      "claude_design",
      "crm",
      "email_campaign",
      "figma",
      "gamma",
      "google_drive",
      "stitch",
    ]);
  });
});
