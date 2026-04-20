-- Loop 4 Phase 3 — PostgreSQL Row-Level Security tenant isolation.
--
-- See ADR-015 (RLS enforcement mode + withTenantContext pattern) and
-- IWO3_LOOP_4_APPROVAL_DECISIONS §Q3 (`confirm` FORCE RLS) + §Q4
-- (`keep_both` JOIN filters + RLS belt-and-suspenders through Loop 10).
--
-- Enforcement mode: ENABLE + FORCE ROW LEVEL SECURITY on 25 tenant-scoped
-- tables. Tenant-agnostic (excluded): permissions, role_permissions,
-- adapter_catalog, adapter_actions, migration_source_manifest.
--
-- Role model:
--   iwo3       — superuser + BYPASSRLS (default POSTGRES_USER attribute).
--                Used by migrations, seeds, admin ops, existing integration
--                tests. RLS is silently bypassed; §Q4 JOIN filters remain
--                the primary isolation for those code paths.
--   iwo3_app   — new NOLOGIN role, non-superuser, no-bypass-rls. iwo3 has
--                membership in iwo3_app (so `SET ROLE` works). Runtime
--                handlers wrap DB work in `withTenantContext`, which
--                opens a transaction, runs SET LOCAL ROLE iwo3_app +
--                SET LOCAL app.current_client_id = <uuid>, and then RLS
--                policies fire on every query.
--
-- Policy template for tables with a direct `client_id` column:
--   USING      (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
--   WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
--
-- Nested tables (no direct client_id) use EXISTS against the closest
-- parent that carries client_id. Partition children of action_audit_log
-- inherit the parent's policies automatically in PG 16.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'iwo3_app') THEN
    CREATE ROLE iwo3_app NOLOGIN;
  END IF;
END$$;
--> statement-breakpoint
GRANT iwo3_app TO iwo3;
--> statement-breakpoint
GRANT USAGE ON SCHEMA public TO iwo3_app;
--> statement-breakpoint
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO iwo3_app;
--> statement-breakpoint
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO iwo3_app;
--> statement-breakpoint
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO iwo3_app;
--> statement-breakpoint
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO iwo3_app;
--> statement-breakpoint

-- ── clients (special: id IS the tenant) ──────────────────────────────
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE clients FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY clients_tenant_iso ON clients FOR ALL
  USING (id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

-- ── users (special: read-only via shared membership; no write policy) ─
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE users FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY users_tenant_read ON users FOR SELECT
  USING (id IN (
    SELECT user_id FROM client_memberships
    WHERE client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
      AND status = 'active'
  ));
--> statement-breakpoint

-- ── Direct client_id column (18 tables) ──────────────────────────────
ALTER TABLE client_memberships ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE client_memberships FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY client_memberships_tenant_iso ON client_memberships FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE template_profiles ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE template_profiles FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY template_profiles_tenant_iso ON template_profiles FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE prompt_profiles ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE prompt_profiles FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY prompt_profiles_tenant_iso ON prompt_profiles FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE prompt_rendered_snapshots ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE prompt_rendered_snapshots FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY prompt_rendered_snapshots_tenant_iso ON prompt_rendered_snapshots FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE repository_bindings ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE repository_bindings FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY repository_bindings_tenant_iso ON repository_bindings FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE data_source_bindings ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE data_source_bindings FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY data_source_bindings_tenant_iso ON data_source_bindings FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE artifacts FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY artifacts_tenant_iso ON artifacts FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE action_audit_log ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE action_audit_log FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY action_audit_log_tenant_iso ON action_audit_log FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE work_orders ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE work_orders FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY work_orders_tenant_iso ON work_orders FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE workflows FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY workflows_tenant_iso ON workflows FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE workflow_executions ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE workflow_executions FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY workflow_executions_tenant_iso ON workflow_executions FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE execution_cycles ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE execution_cycles FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY execution_cycles_tenant_iso ON execution_cycles FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE client_adapter_configs ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE client_adapter_configs FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY client_adapter_configs_tenant_iso ON client_adapter_configs FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE adapter_action_policies ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE adapter_action_policies FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY adapter_action_policies_tenant_iso ON adapter_action_policies FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE adapter_credentials ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE adapter_credentials FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY adapter_credentials_tenant_iso ON adapter_credentials FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE output_packages ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE output_packages FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY output_packages_tenant_iso ON output_packages FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE output_handoffs ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE output_handoffs FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY output_handoffs_tenant_iso ON output_handoffs FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

ALTER TABLE permission_grants ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE permission_grants FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY permission_grants_tenant_iso ON permission_grants FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

-- ── Nested tables — EXISTS via parent (5 tables) ─────────────────────

-- workflow_templates → workflows (client_id)
ALTER TABLE workflow_templates ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE workflow_templates FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY workflow_templates_tenant_iso ON workflow_templates FOR ALL
  USING (EXISTS (
    SELECT 1 FROM workflows w
    WHERE w.id = workflow_templates.workflow_id
      AND w.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM workflows w
    WHERE w.id = workflow_templates.workflow_id
      AND w.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ));
--> statement-breakpoint

-- workflow_template_steps → workflow_templates → workflows
ALTER TABLE workflow_template_steps ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE workflow_template_steps FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY workflow_template_steps_tenant_iso ON workflow_template_steps FOR ALL
  USING (EXISTS (
    SELECT 1 FROM workflow_templates wt
    JOIN workflows w ON w.id = wt.workflow_id
    WHERE wt.id = workflow_template_steps.template_id
      AND w.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM workflow_templates wt
    JOIN workflows w ON w.id = wt.workflow_id
    WHERE wt.id = workflow_template_steps.template_id
      AND w.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ));
--> statement-breakpoint

-- workflow_step_runs → workflow_executions (client_id)
ALTER TABLE workflow_step_runs ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE workflow_step_runs FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY workflow_step_runs_tenant_iso ON workflow_step_runs FOR ALL
  USING (EXISTS (
    SELECT 1 FROM workflow_executions we
    WHERE we.id = workflow_step_runs.execution_id
      AND we.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM workflow_executions we
    WHERE we.id = workflow_step_runs.execution_id
      AND we.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ));
--> statement-breakpoint

-- prompt_profile_versions → prompt_profiles (client_id)
ALTER TABLE prompt_profile_versions ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE prompt_profile_versions FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY prompt_profile_versions_tenant_iso ON prompt_profile_versions FOR ALL
  USING (EXISTS (
    SELECT 1 FROM prompt_profiles pp
    WHERE pp.id = prompt_profile_versions.profile_id
      AND pp.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM prompt_profiles pp
    WHERE pp.id = prompt_profile_versions.profile_id
      AND pp.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ));
--> statement-breakpoint

-- external_execution_results → output_handoffs (client_id)
ALTER TABLE external_execution_results ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE external_execution_results FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY external_execution_results_tenant_iso ON external_execution_results FOR ALL
  USING (EXISTS (
    SELECT 1 FROM output_handoffs oh
    WHERE oh.id = external_execution_results.output_handoff_id
      AND oh.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM output_handoffs oh
    WHERE oh.id = external_execution_results.output_handoff_id
      AND oh.client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
  ));
