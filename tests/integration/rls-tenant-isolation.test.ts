import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

import { withTenantContext } from "../../packages/contracts/db/tenant_context";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR = "00000000-0000-4000-8000-00000000c001";
const FFAI = "00000000-0000-4000-8000-00000000c002";
const KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003";

describeIwo3("Loop 4 Phase 3 — RLS tenant isolation", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("withTenantContext=Klear sees exactly one client row (Klear)", async () => {
    const rows = await withTenantContext(
      pool,
      { clientId: KLEAR },
      async (c) => {
        const { rows } = await c.query<{ designation: string; id: string }>(
          `SELECT id, designation FROM clients`
        );
        return rows;
      }
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe(KLEAR);
    expect(rows[0].designation).toBe("IWO | Klear.ai");
  });

  it("withTenantContext=FFAI sees only FFAI workflows (Klear rows hidden)", async () => {
    const rows = await withTenantContext(
      pool,
      { clientId: FFAI },
      async (c) => {
        const { rows } = await c.query<{ client_id: string; key: string }>(
          `SELECT client_id, key FROM workflows ORDER BY key`
        );
        return rows;
      }
    );
    expect(rows.length).toBeGreaterThanOrEqual(1);
    for (const r of rows) {
      expect(r.client_id, `cross-tenant bleed on row ${r.key}`).toBe(FFAI);
    }
  });

  it("iwo3_app role without SET app.current_client_id returns 0 tenant rows", async () => {
    const c = await pool.connect();
    try {
      await c.query("BEGIN");
      await c.query("SET LOCAL ROLE iwo3_app");
      // Deliberately skip `app.current_client_id` — policies should see
      // NULL → cast fails silently → `client_id = NULL` → false → 0 rows.
      const { rows: wo } = await c.query(
        `SELECT client_id FROM work_orders`
      );
      const { rows: cl } = await c.query(
        `SELECT id FROM clients`
      );
      expect(wo).toHaveLength(0);
      expect(cl).toHaveLength(0);
      await c.query("ROLLBACK");
    } finally {
      c.release();
    }
  });

  it("WITH CHECK blocks cross-tenant INSERT — Klear context cannot insert FFAI-owned row", async () => {
    await expect(
      withTenantContext(pool, { clientId: KLEAR }, async (c) => {
        await c.query(
          `INSERT INTO artifacts
             (client_id, source_type, content_class, storage_ref, created_by_user_id, metadata)
           VALUES ($1::uuid, 'upload', 'c0', 'memory://rls-check',
                   $2::uuid, $3::jsonb)`,
          [
            FFAI,
            KLEAR_OPERATOR,
            JSON.stringify({ test_marker: "rls-with-check-cross-tenant" }),
          ]
        );
      })
    ).rejects.toThrow(/row.level security|violates row-level security policy/i);
  });

  it("Klear-owned INSERT under Klear context succeeds + is readable by the same context", async () => {
    let newId: string | null = null;
    try {
      newId = await withTenantContext(pool, { clientId: KLEAR }, async (c) => {
        const { rows } = await c.query<{ id: string }>(
          `INSERT INTO artifacts
             (client_id, source_type, content_class, storage_ref, created_by_user_id, metadata)
           VALUES ($1::uuid, 'upload', 'c0', 'memory://rls-ok',
                   $2::uuid, $3::jsonb)
           RETURNING id`,
          [
            KLEAR,
            KLEAR_OPERATOR,
            JSON.stringify({ test_marker: "rls-ok-insert" }),
          ]
        );
        return rows[0].id;
      });
      expect(newId).toMatch(/^[0-9a-f-]{36}$/);

      // Read under FFAI context → should not see Klear row.
      const ffaiRows = await withTenantContext(
        pool,
        { clientId: FFAI },
        async (c) => {
          const { rows } = await c.query(
            `SELECT id FROM artifacts WHERE id = $1`,
            [newId]
          );
          return rows;
        }
      );
      expect(ffaiRows).toHaveLength(0);

      // Read under Klear context → should see it.
      const klearRows = await withTenantContext(
        pool,
        { clientId: KLEAR },
        async (c) => {
          const { rows } = await c.query(
            `SELECT id FROM artifacts WHERE id = $1`,
            [newId]
          );
          return rows;
        }
      );
      expect(klearRows).toHaveLength(1);
    } finally {
      if (newId) {
        // Cleanup as iwo3 superuser (bypass RLS).
        await pool.query(`DELETE FROM artifacts WHERE id = $1`, [newId]);
      }
    }
  });

  it("nested table (workflow_templates → workflows) isolates via parent JOIN", async () => {
    const klearTemplates = await withTenantContext(
      pool,
      { clientId: KLEAR },
      async (c) => {
        const { rows } = await c.query<{ id: string; workflow_id: string }>(
          `SELECT id, workflow_id FROM workflow_templates`
        );
        return rows;
      }
    );
    // Every returned template must JOIN to a Klear workflow.
    for (const r of klearTemplates) {
      const { rows: parent } = await pool.query<{ client_id: string }>(
        `SELECT client_id FROM workflows WHERE id = $1`,
        [r.workflow_id]
      );
      expect(parent[0].client_id).toBe(KLEAR);
    }
  });

  it("nested table (external_execution_results → output_handoffs) isolates via parent", async () => {
    // No fresh rows in the seed baseline — insert one under Klear context,
    // then prove FFAI can't see it.
    let eid: string | null = null;
    let hid: string | null = null;
    try {
      const inserted = await withTenantContext(
        pool,
        { clientId: KLEAR },
        async (c) => {
          // Reuse an existing output_package_id from the seeded Klear WO flow.
          // Minimum shape: create an output_handoffs row under Klear.
          const pkgRes = await c.query<{ id: string }>(
            `INSERT INTO output_packages
               (client_id, output_kind, title, content_blocks,
                created_by_user_id, provenance)
             VALUES ($1::uuid, 'gamma_pptx', 'rls-nested-test',
                     $2::jsonb, $3::uuid, $4::jsonb)
             RETURNING id`,
            [
              KLEAR,
              JSON.stringify({ sections: [{ title: "t", body: "b" }] }),
              KLEAR_OPERATOR,
              JSON.stringify({ test_marker: "rls-nested-eer" }),
            ]
          );
          const handoffRes = await c.query<{ id: string }>(
            `INSERT INTO output_handoffs
               (client_id, output_package_id, status, metadata)
             VALUES ($1::uuid, $2::uuid, 'queued', $3::jsonb)
             RETURNING id`,
            [
              KLEAR,
              pkgRes.rows[0].id,
              JSON.stringify({ test_marker: "rls-nested-eer" }),
            ]
          );
          const eerRes = await c.query<{ id: string }>(
            `INSERT INTO external_execution_results
               (output_handoff_id, status, metadata)
             VALUES ($1::uuid, 'success', $2::jsonb)
             RETURNING id`,
            [
              handoffRes.rows[0].id,
              JSON.stringify({ test_marker: "rls-nested-eer" }),
            ]
          );
          return {
            eerId: eerRes.rows[0].id,
            handoffId: handoffRes.rows[0].id,
            pkgId: pkgRes.rows[0].id,
          };
        }
      );
      eid = inserted.eerId;
      hid = inserted.handoffId;

      // FFAI context: external_execution_results row hidden via parent-JOIN.
      const ffaiRows = await withTenantContext(
        pool,
        { clientId: FFAI },
        async (c) => {
          const { rows } = await c.query(
            `SELECT id FROM external_execution_results WHERE id = $1`,
            [eid]
          );
          return rows;
        }
      );
      expect(ffaiRows).toHaveLength(0);

      // Klear context: row visible.
      const klearRows = await withTenantContext(
        pool,
        { clientId: KLEAR },
        async (c) => {
          const { rows } = await c.query(
            `SELECT id FROM external_execution_results WHERE id = $1`,
            [eid]
          );
          return rows;
        }
      );
      expect(klearRows).toHaveLength(1);
    } finally {
      if (eid) {
        await pool.query(
          `DELETE FROM external_execution_results WHERE id = $1`,
          [eid]
        );
      }
      if (hid) {
        await pool.query(`DELETE FROM output_handoffs WHERE id = $1`, [hid]);
        await pool.query(
          `DELETE FROM output_packages
           WHERE provenance->>'test_marker' = 'rls-nested-eer'`
        );
      }
    }
  });

  it("admin iwo3 (superuser+BYPASSRLS) still sees both tenants — §Q4 keep_both belt", async () => {
    const { rows } = await pool.query<{ client_id: string }>(
      `SELECT DISTINCT client_id FROM work_orders`
    );
    const tenants = new Set(rows.map((r) => r.client_id));
    expect(tenants.has(KLEAR)).toBe(true);
    expect(tenants.has(FFAI)).toBe(true);
  });

  it("users table is readable via shared membership but not writable from iwo3_app", async () => {
    // Under Klear context, we can SELECT users that have an active Klear
    // membership (includes the Klear operator).
    const klearVisible = await withTenantContext(
      pool,
      { clientId: KLEAR },
      async (c) => {
        const { rows } = await c.query<{ email: string }>(
          `SELECT email FROM users ORDER BY email`
        );
        return rows;
      }
    );
    expect(klearVisible.length).toBeGreaterThanOrEqual(6);
    const emails = new Set(klearVisible.map((r) => r.email));
    expect(emails.has("operator_klear@dev.local")).toBe(true);
    // `intruder@dev.local` has no membership, so is not visible here.
    expect(emails.has("intruder@dev.local")).toBe(false);

    // INSERT as iwo3_app should be blocked — users has no INSERT policy.
    await expect(
      withTenantContext(pool, { clientId: KLEAR }, async (c) => {
        await c.query(
          `INSERT INTO users (email, display_name, status)
           VALUES ('rls-blocked@test.local', 'Should Not Exist', 'active')`
        );
      })
    ).rejects.toThrow();
  });
});
