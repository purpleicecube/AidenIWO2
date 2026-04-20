import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

// Tenant-scoped tables per ADR-015 / migration 0006. 25 tables.
// Keep this list in sync with the migration comment.
const TENANT_SCOPED_TABLES: readonly string[] = [
  // clients (special — id IS tenant) + users (special — read-only)
  "clients",
  "users",
  // direct client_id (18)
  "client_memberships",
  "template_profiles",
  "prompt_profiles",
  "prompt_rendered_snapshots",
  "repository_bindings",
  "data_source_bindings",
  "artifacts",
  "action_audit_log",
  "work_orders",
  "workflows",
  "workflow_executions",
  "execution_cycles",
  "client_adapter_configs",
  "adapter_action_policies",
  "adapter_credentials",
  "output_packages",
  "output_handoffs",
  "permission_grants",
  // nested via parent JOIN (5)
  "workflow_templates",
  "workflow_template_steps",
  "workflow_step_runs",
  "prompt_profile_versions",
  "external_execution_results",
];

// Tables explicitly excluded from RLS — tenant-agnostic vocabularies.
const TENANT_AGNOSTIC_TABLES: readonly string[] = [
  "permissions",
  "role_permissions",
  "adapter_catalog",
  "adapter_actions",
  "migration_source_manifest",
];

describeIwo3("Loop 4 Phase 3 — RLS force-enabled invariant", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("every tenant-scoped table has ENABLE + FORCE ROW LEVEL SECURITY", async () => {
    const { rows } = await pool.query<{
      table_name: string;
      rowsecurity: boolean;
      forcerowsecurity: boolean;
    }>(
      `SELECT c.relname AS table_name,
              c.relrowsecurity AS rowsecurity,
              c.relforcerowsecurity AS forcerowsecurity
       FROM pg_class c
       JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'public' AND c.relname = ANY($1)
       ORDER BY c.relname`,
      [TENANT_SCOPED_TABLES as string[]]
    );
    expect(rows).toHaveLength(TENANT_SCOPED_TABLES.length);
    for (const r of rows) {
      expect(r.rowsecurity, `ENABLE RLS on ${r.table_name}`).toBe(true);
      expect(r.forcerowsecurity, `FORCE RLS on ${r.table_name}`).toBe(true);
    }
  });

  it("tenant-agnostic tables do NOT have row-level security", async () => {
    const { rows } = await pool.query<{
      table_name: string;
      rowsecurity: boolean;
      forcerowsecurity: boolean;
    }>(
      `SELECT c.relname AS table_name,
              c.relrowsecurity AS rowsecurity,
              c.relforcerowsecurity AS forcerowsecurity
       FROM pg_class c
       JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'public' AND c.relname = ANY($1)
       ORDER BY c.relname`,
      [TENANT_AGNOSTIC_TABLES as string[]]
    );
    expect(rows).toHaveLength(TENANT_AGNOSTIC_TABLES.length);
    for (const r of rows) {
      expect(r.rowsecurity, `${r.table_name} should not have RLS`).toBe(false);
      expect(r.forcerowsecurity, `${r.table_name} should not FORCE`).toBe(
        false
      );
    }
  });

  it("every tenant-scoped table has at least one policy attached", async () => {
    const { rows } = await pool.query<{ tablename: string; count: string }>(
      `SELECT tablename, count(*) AS count
       FROM pg_policies
       WHERE schemaname = 'public'
         AND tablename = ANY($1)
       GROUP BY tablename`,
      [TENANT_SCOPED_TABLES as string[]]
    );
    const policyMap = Object.fromEntries(
      rows.map((r) => [r.tablename, Number(r.count)])
    );
    for (const t of TENANT_SCOPED_TABLES) {
      expect(policyMap[t], `policy count on ${t}`).toBeGreaterThanOrEqual(1);
    }
  });

  it("iwo3_app role exists, NOLOGIN, non-superuser, no BYPASSRLS", async () => {
    const { rows } = await pool.query<{
      rolsuper: boolean;
      rolbypassrls: boolean;
      rolcanlogin: boolean;
    }>(
      `SELECT rolsuper, rolbypassrls, rolcanlogin
       FROM pg_roles WHERE rolname = 'iwo3_app'`
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].rolsuper).toBe(false);
    expect(rows[0].rolbypassrls).toBe(false);
    expect(rows[0].rolcanlogin).toBe(false);
  });

  it("iwo3 is a member of iwo3_app (SET ROLE works)", async () => {
    const { rows } = await pool.query(
      `SELECT 1
       FROM pg_auth_members m
       JOIN pg_roles r ON r.oid = m.roleid
       JOIN pg_roles u ON u.oid = m.member
       WHERE r.rolname = 'iwo3_app' AND u.rolname = 'iwo3'`
    );
    expect(rows).toHaveLength(1);
  });
});
