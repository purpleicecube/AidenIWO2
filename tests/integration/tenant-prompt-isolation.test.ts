import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const OPERATOR_KLEAR = "operator_klear@dev.local";
const OPERATOR_FFAI = "operator_ffai@dev.local";
const SUPER = "super@dev.local";
const INTRUDER = "intruder@dev.local";

// Service-layer tenant filter simulation. Matches the query shape that
// every prompt-profile read path must use in Loop 3+ (JOIN through
// client_memberships; no rows for users without active membership).
const LIST_PROFILES_FOR_USER = `
  SELECT pp.id, pp.profile_key, c.designation
  FROM prompt_profiles pp
  JOIN clients c ON c.id = pp.client_id
  JOIN client_memberships m ON m.client_id = pp.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, pp.profile_key
`;

describeIwo3("Loop 2 Phase 2 — tenant prompt isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  it("Klear Operator sees only the Klear prompt profile", async () => {
    const { rows } = await pool.query<{
      profile_key: string;
      designation: string;
    }>(LIST_PROFILES_FOR_USER, [OPERATOR_KLEAR]);
    expect(rows.map((r) => r.profile_key)).toEqual(["klear_brand_v1"]);
    expect(rows[0].designation).toBe("IWO | Klear.ai");
  });

  it("FFAI Operator sees only the FFAI prompt profile", async () => {
    const { rows } = await pool.query<{
      profile_key: string;
      designation: string;
    }>(LIST_PROFILES_FOR_USER, [OPERATOR_FFAI]);
    expect(rows.map((r) => r.profile_key)).toEqual(["ffai_brand_v1"]);
    expect(rows[0].designation).toBe("IWO | FreedomForge.AI");
  });

  it("super user (owner on both tenants) sees both profiles", async () => {
    const { rows } = await pool.query<{
      profile_key: string;
      designation: string;
    }>(LIST_PROFILES_FOR_USER, [SUPER]);
    expect(rows.map((r) => r.profile_key).sort()).toEqual([
      "ffai_brand_v1",
      "klear_brand_v1",
    ]);
  });

  it("intruder (no memberships) sees zero profiles", async () => {
    const { rows } = await pool.query(LIST_PROFILES_FOR_USER, [INTRUDER]);
    expect(rows).toHaveLength(0);
  });
});
