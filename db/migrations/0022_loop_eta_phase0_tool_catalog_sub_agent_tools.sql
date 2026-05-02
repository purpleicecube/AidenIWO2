-- Loop Eta phase 0 — global tool catalog + per-(tenant, llm_config) tool assignments.
-- See IWO3_LOOP_ETA_SCOPE_PROPOSAL §3 for the schema design.
--
-- Three deltas:
--   1. tool_catalog (tenant-agnostic registry) + 3 enums + 2 indexes
--   2. sub_agent_tools (tenant-scoped assignments) + RLS FORCE policy
--   3. llm_configs.metadata (jsonb, optional) — carries prompt_provenance
--      and other future per-row metadata without further migrations.
--
-- The runtime registry stays in code (apps/api-fastapi/runtime/aiden_tools.py).
-- This migration provides the metadata + assignment surface for the IWO2-style
-- Sub-Agents UI and the Tier 2 tool-call -> execute -> re-invoke loop.

-- ── Enums ──────────────────────────────────────────────────────────

CREATE TYPE "tool_category" AS ENUM (
  'search',
  'document',
  'rendering',
  'design',
  'data',
  'ops',
  'introspection',
  'skill_only'
);

CREATE TYPE "tool_runtime_status" AS ENUM (
  'runnable',
  'skill_only',
  'mcp',
  'planned'
);

CREATE TYPE "tool_default_tier" AS ENUM (
  'tier_1',
  'tier_2',
  'either'
);

-- ── tool_catalog (tenant-agnostic) ─────────────────────────────────

CREATE TABLE IF NOT EXISTS "tool_catalog" (
  "id"              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "tool_key"        varchar(96)  NOT NULL UNIQUE,
  "display_name"    varchar(160) NOT NULL,
  "description"     text         NOT NULL,
  "category"        tool_category        NOT NULL,
  "runtime_status"  tool_runtime_status  NOT NULL,
  "args_schema"     jsonb        NOT NULL DEFAULT '{}'::jsonb,
  "handler_ref"     varchar(256),
  "default_tier"    tool_default_tier    NOT NULL,
  "iwo2_origin"     varchar(96),
  "enabled"         boolean      NOT NULL DEFAULT true,
  "notes"           text,
  "created_at"      timestamp with time zone NOT NULL DEFAULT now(),
  "updated_at"      timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS "tool_catalog_category_status_idx"
  ON "tool_catalog" ("category", "runtime_status");

CREATE INDEX IF NOT EXISTS "tool_catalog_default_tier_idx"
  ON "tool_catalog" ("default_tier");

-- tool_catalog is tenant-agnostic. Per Loop 4 Phase 4.3 pattern,
-- tenant-agnostic tables (permissions, role_permissions, adapter_catalog,
-- adapter_actions, migration_source_manifest) are excluded from the RLS
-- FORCE list. iwo3_app gets full SELECT access; mutations route through
-- routes/tool_catalog (admin-gated via tool_catalog:write).
GRANT SELECT, INSERT, UPDATE, DELETE ON "tool_catalog" TO iwo3_app;

-- ── sub_agent_tools (tenant-scoped) ────────────────────────────────

CREATE TABLE IF NOT EXISTS "sub_agent_tools" (
  "id"                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "client_id"           uuid NOT NULL REFERENCES "clients"("id") ON DELETE CASCADE,
  "llm_config_id"       uuid NOT NULL REFERENCES "llm_configs"("id") ON DELETE CASCADE,
  "tool_key"            varchar(96) NOT NULL REFERENCES "tool_catalog"("tool_key") ON DELETE RESTRICT,
  "enabled"             boolean NOT NULL DEFAULT true,
  "granted_at"          timestamp with time zone NOT NULL DEFAULT now(),
  "granted_by_user_id"  uuid REFERENCES "users"("id") ON DELETE SET NULL,
  "notes"               text,
  CONSTRAINT "sub_agent_tools_unique_per_config_tool"
    UNIQUE ("llm_config_id", "tool_key")
);

CREATE INDEX IF NOT EXISTS "sub_agent_tools_tenant_config_idx"
  ON "sub_agent_tools" ("client_id", "llm_config_id");

CREATE INDEX IF NOT EXISTS "sub_agent_tools_tool_key_idx"
  ON "sub_agent_tools" ("tool_key");

ALTER TABLE "sub_agent_tools" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "sub_agent_tools" FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policy WHERE polname = 'sub_agent_tools_tenant_isolation'
  ) THEN
    CREATE POLICY "sub_agent_tools_tenant_isolation"
      ON "sub_agent_tools"
      USING (
        "client_id" = NULLIF(current_setting('app.current_client_id', true), '')::uuid
      )
      WITH CHECK (
        "client_id" = NULLIF(current_setting('app.current_client_id', true), '')::uuid
      );
  END IF;
END$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON "sub_agent_tools" TO iwo3_app;

-- ── llm_configs.metadata jsonb ─────────────────────────────────────
-- Loop Eta extends llm_configs with a flexible metadata jsonb field. The
-- first consumer is `metadata.prompt_provenance` ∈ {extracted_from_iwo2_live,
-- extracted_from_iwo2_static, authored_parity_approximation, authored_net_new}
-- per IWO3_LOOP_ETA_SCOPE_PROPOSAL §1. Future per-row metadata can land here
-- without further migrations.

ALTER TABLE "llm_configs"
  ADD COLUMN IF NOT EXISTS "metadata" jsonb;
