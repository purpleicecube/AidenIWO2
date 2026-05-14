/**
 * Loop CAP-A Φ.1 — client_brand_profiles RLS tenant isolation.
 *
 * Asserts the new client_brand_profiles table honors the canonical
 * IWO3 RLS posture (ENABLE + FORCE + nullif()::uuid GUC pattern,
 * ADR-014):
 *   1. withTenantContext=Klear sees exactly one row, its own.
 *   2. withTenantContext=FFAI sees exactly one row, its own.
 *   3. iwo3_app without `app.current_client_id` set sees zero rows.
 *   4. WITH CHECK blocks cross-tenant INSERT (Klear context cannot
 *      insert an FFAI-owned brand profile row).
 *   5. UNIQUE (client_id) — exactly one current brand profile per
 *      tenant; second insert under the same tenant context fails.
 */

import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

import { withTenantContext } from "../../packages/contracts/db/tenant_context";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR = "00000000-0000-4000-8000-00000000c001";
const FFAI = "00000000-0000-4000-8000-00000000c002";

describeIwo3("Loop CAP-A Φ.1 — client_brand_profiles RLS tenant isolation", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("withTenantContext=Klear sees exactly one row (Klear's brand profile)", async () => {
    const rows = await withTenantContext(
      pool,
      { clientId: KLEAR },
      async (c) => {
        const { rows } = await c.query<{ client_id: string }>(
          `SELECT client_id FROM client_brand_profiles`
        );
        return rows;
      }
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].client_id).toBe(KLEAR);
  });

  it("withTenantContext=FFAI sees exactly one row (FFAI's brand profile)", async () => {
    const rows = await withTenantContext(
      pool,
      { clientId: FFAI },
      async (c) => {
        const { rows } = await c.query<{ client_id: string }>(
          `SELECT client_id FROM client_brand_profiles`
        );
        return rows;
      }
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].client_id).toBe(FFAI);
  });

  it("iwo3_app without app.current_client_id GUC returns 0 brand_profile rows", async () => {
    const c = await pool.connect();
    try {
      await c.query("BEGIN");
      await c.query("SET LOCAL ROLE iwo3_app");
      // Deliberately skip set_config — policy should see NULL → cast
      // fails silently → client_id = NULL → false → 0 rows.
      const { rows } = await c.query(
        `SELECT client_id FROM client_brand_profiles`
      );
      expect(rows).toHaveLength(0);
      await c.query("ROLLBACK");
    } finally {
      c.release();
    }
  });

  it("WITH CHECK blocks cross-tenant INSERT — Klear context cannot insert FFAI-owned brand profile", async () => {
    await expect(
      withTenantContext(pool, { clientId: KLEAR }, async (c) => {
        await c.query(
          `INSERT INTO client_brand_profiles (client_id, brand_terms)
           VALUES ($1::uuid, ARRAY[]::text[])`,
          [FFAI]
        );
      })
    ).rejects.toThrow();
  });

  it("UNIQUE (client_id) blocks a second brand_profile row for the same tenant", async () => {
    // Klear already has its seed row; attempting to insert a second
    // row with the same client_id should fail on the unique constraint.
    await expect(
      withTenantContext(pool, { clientId: KLEAR }, async (c) => {
        await c.query(
          `INSERT INTO client_brand_profiles (client_id, brand_terms)
           VALUES ($1::uuid, ARRAY[]::text[])`,
          [KLEAR]
        );
      })
    ).rejects.toThrow(/client_brand_profiles_client_id_uniq/);
  });
});
