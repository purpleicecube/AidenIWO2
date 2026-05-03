-- 0023_loop_theta_tool_locker.sql
--
-- MegaLoop Theta — Tools Locker port from IWO2.
--
-- Schema delta to give the existing tool_catalog row shape full IWO2
-- parity for the operator-facing /tools page (Tools Locker). The
-- catalog was Loop-Eta-shipped as a 9-column registry; this migration
-- adds the 24 fields IWO2 carried so operators can deploy/edit/import
-- skills + MCP servers + API/CLI/webhook tools end-to-end.
--
-- Sequence:
--   1. New ENUMs: tool_type (7 IWO2 values), tool_access_tier (3 values).
--   2. ALTER TABLE tool_catalog ADD COLUMN ... (24 new fields, all
--      NULLABLE or with sensible defaults so the existing 29 rows stay
--      valid).
--   3. Backfill `tool_type` for the seeded rows so the Identity tab
--      surfaces the correct radio choice on first render.
--   4. CREATE TABLE tool_tags + tool_tag_assignments (discovery
--      metadata; UI surface deferred per scope §Out-of-scope).
--   5. GRANT SELECT/INSERT/UPDATE/DELETE on the new tables to iwo3_app.
--   6. INSERT manifest rows for tool_tags + tool_tag_assignments under
--      iwo3_native/drizzle.
--
-- Dependencies: migration 0022 (tool_catalog + sub_agent_tools).

-- ── 1. ENUMs ──────────────────────────────────────────────────────

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tool_type') THEN
    CREATE TYPE "tool_type" AS ENUM (
      'skill',
      'python_code',
      'slash_command',
      'cli',
      'api',
      'webhook',
      'mcp_server'
    );
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tool_access_tier') THEN
    CREATE TYPE "tool_access_tier" AS ENUM (
      'any',
      'tier_1',
      'tier_2'
    );
  END IF;
END$$;

-- ── 2. Extend tool_catalog ────────────────────────────────────────

ALTER TABLE "tool_catalog"
  ADD COLUMN IF NOT EXISTS "tool_type"             "tool_type",
  ADD COLUMN IF NOT EXISTS "version_label"         varchar(32) NOT NULL DEFAULT '1.0.0',
  ADD COLUMN IF NOT EXISTS "execution_mode"        varchar(64) NOT NULL DEFAULT 'prompt_injection',
  ADD COLUMN IF NOT EXISTS "skill_content"         text,
  ADD COLUMN IF NOT EXISTS "skill_instructions"    text,
  ADD COLUMN IF NOT EXISTS "trigger_conditions"    jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS "source_code"           text,
  ADD COLUMN IF NOT EXISTS "entry_point"           varchar(256),
  ADD COLUMN IF NOT EXISTS "runtime_environment"   varchar(64),
  ADD COLUMN IF NOT EXISTS "sandbox_config"        jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS "mcp_config"            jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS "credentials"           jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS "usage_instructions"    text,
  ADD COLUMN IF NOT EXISTS "input_schema"          jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS "output_schema"         jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS "access_tier"           "tool_access_tier" NOT NULL DEFAULT 'any',
  ADD COLUMN IF NOT EXISTS "max_concurrent"        integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS "default_lease_seconds" integer NOT NULL DEFAULT 300,
  ADD COLUMN IF NOT EXISTS "max_lease_seconds"     integer NOT NULL DEFAULT 3600,
  ADD COLUMN IF NOT EXISTS "daily_usage_limit"     integer,
  ADD COLUMN IF NOT EXISTS "cost_ceiling_per_day"  text,
  ADD COLUMN IF NOT EXISTS "requires_approval"     boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS "restricted"            boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS "restricted_reason"     text,
  ADD COLUMN IF NOT EXISTS "restricted_by_user_id" uuid REFERENCES "users"("id") ON DELETE SET NULL;

-- ── 3. Backfill tool_type for the 29 seeded Loop Eta rows ─────────
-- Per scope §D9: tool_type and runtime_status answer different
-- questions. Backfill from a hand-curated mapping reflecting how each
-- runnable handler is wired (api / python_code / mcp_server) and
-- marking every *_skill row as 'skill'.

UPDATE "tool_catalog" SET "tool_type" = 'api'::tool_type
  WHERE "tool_key" IN (
    'web_search_brave',
    'web_search_perplexity',
    'web_search_ddg',
    'web_scrape',
    'gamma_render',
    'http_health_probe'
  );

UPDATE "tool_catalog" SET "tool_type" = 'python_code'::tool_type
  WHERE "tool_key" IN (
    'pdf_extract_text',
    'csv_validate',
    'markdown_to_pptx',
    'runtime_health',
    'work_order_counts',
    'recent_work_orders'
  );

UPDATE "tool_catalog" SET "tool_type" = 'mcp_server'::tool_type
  WHERE "tool_key" = 'stitch_design';

UPDATE "tool_catalog" SET "tool_type" = 'skill'::tool_type
  WHERE "tool_key" LIKE '%_skill';

-- After backfill, every existing row should carry a tool_type. New
-- rows must explicitly set it (the API enforces this via Pydantic
-- validation; the column is left nullable so the schema add-column
-- stays single-pass — the API contract is the canonical gate).

-- ── 4. tool_tags + tool_tag_assignments ───────────────────────────

CREATE TABLE IF NOT EXISTS "tool_tags" (
  "id"          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "name"        varchar(64) NOT NULL UNIQUE,
  "category"    varchar(64) NOT NULL DEFAULT 'general',
  "description" text,
  "color"       varchar(16) DEFAULT '#6366f1',
  "created_at"  timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS "tool_tag_assignments" (
  "id"               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "tool_catalog_id"  uuid NOT NULL REFERENCES "tool_catalog"("id") ON DELETE CASCADE,
  "tag_id"           uuid NOT NULL REFERENCES "tool_tags"("id") ON DELETE CASCADE,
  "assigned_at"      timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "tool_tag_assignments_unique"
    UNIQUE ("tool_catalog_id", "tag_id")
);

CREATE INDEX IF NOT EXISTS "tool_tag_assignments_tool_idx"
  ON "tool_tag_assignments" ("tool_catalog_id");

CREATE INDEX IF NOT EXISTS "tool_tag_assignments_tag_idx"
  ON "tool_tag_assignments" ("tag_id");

-- ── 5. GRANTs for iwo3_app ────────────────────────────────────────

GRANT SELECT, INSERT, UPDATE, DELETE ON "tool_tags" TO iwo3_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON "tool_tag_assignments" TO iwo3_app;

-- ── 6. Manifest entries ───────────────────────────────────────────

INSERT INTO "migration_source_manifest"
  ("table_name", "source", "source_version", "owned_by", "notes")
VALUES
  ('tool_tags',
   'iwo3_native',
   'iwo3@v0.5.0-loop-theta',
   'drizzle',
   'MegaLoop Theta — discovery metadata for Tools Locker. UI surface deferred per scope §Out-of-scope; schema is a forward-compat slot.'),
  ('tool_tag_assignments',
   'iwo3_native',
   'iwo3@v0.5.0-loop-theta',
   'drizzle',
   'MegaLoop Theta — many-to-many bridge between tool_catalog rows and tool_tags. CASCADE on both FKs.')
ON CONFLICT ("table_name") DO NOTHING;
