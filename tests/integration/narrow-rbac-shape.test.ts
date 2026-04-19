import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

describeIwo3("Loop 1 — narrow RBAC shape", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("rejects a template_profiles insert without client_id", async () => {
    await expect(
      pool.query(
        `INSERT INTO template_profiles (profile_key, output_kind, engine)
         VALUES ('loop1_bad_insert', 'pptx', 'gamma_basic')`
      )
    ).rejects.toThrow();
  });

  it("returns the Operator role for the seeded Klear operator user", async () => {
    const { rows } = await pool.query<{ role: string }>(
      `SELECT m.role
       FROM client_memberships m
       JOIN clients c ON c.id = m.client_id
       JOIN users u ON u.id = m.user_id
       WHERE c.designation = 'IWO | Klear.ai'
         AND u.email = 'operator_klear@dev.local'`
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].role).toBe("operator");
  });

  it("FFAI viewer has no membership on the Klear tenant (isolation by absence)", async () => {
    const { rows } = await pool.query(
      `SELECT 1
       FROM client_memberships m
       JOIN clients c ON c.id = m.client_id
       JOIN users u ON u.id = m.user_id
       WHERE c.designation = 'IWO | Klear.ai'
         AND u.email = 'viewer_ffai@dev.local'`
    );
    expect(rows).toHaveLength(0);
  });

  it("all three Klear Gamma template profiles are present", async () => {
    const { rows } = await pool.query<{ profile_key: string; external_ref: string }>(
      `SELECT tp.profile_key, tp.external_ref
       FROM template_profiles tp
       JOIN clients c ON c.id = tp.client_id
       WHERE c.designation = 'IWO | Klear.ai'
       ORDER BY tp.profile_key`
    );
    const map = Object.fromEntries(rows.map((r) => [r.profile_key, r.external_ref]));
    expect(map["klear_pptx_primary"]).toBe("g_onfwfqpb52zcws3");
    expect(map["klear_pdf_rmis"]).toBe("g_szfb73vjsyir322");
    expect(map["klear_pdf_claims"]).toBe("g_122ahx4j0eer8lz");
  });
});
