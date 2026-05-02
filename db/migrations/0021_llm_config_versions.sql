-- Beta-2 phase 0.3.1 — versioned history for `llm_configs`.
--
-- Every mutation to `llm_configs` (PATCH, bulk_apply, rollback, create)
-- writes a full-row snapshot here BEFORE the live row is updated, so
-- rollback is "pick a prior snapshot, apply it as a new mutation". No
-- partial state, no parallel storage, no pointer drift.
--
-- Per CODEX 2026-05-01 universal slice (Phase 1):
--   1. Snapshot is full-row (not delta) — simpler rollback semantics,
--      cheaper diff UI, ~1KB per row is fine.
--   2. version_number is monotonic per llm_config_id (1, 2, 3, …).
--   3. change_action records the cause: 'initial' (backfill), 'create',
--      'update', 'rollback'. (bulk_apply uses 'update' per entry.)
--   4. RLS + FORCE — versions inherit the tenant boundary of their
--      parent llm_config.
--   5. iwo3_app gets SELECT + INSERT only — history rows are immutable.
--      Lifecycle (deletion) tied to parent via ON DELETE CASCADE.

CREATE TABLE IF NOT EXISTS "llm_config_versions" (
  "id"              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "llm_config_id"   uuid NOT NULL REFERENCES "llm_configs"("id") ON DELETE CASCADE,
  "client_id"       uuid NOT NULL REFERENCES "clients"("id")    ON DELETE CASCADE,
  "version_number"  integer NOT NULL,

  -- Full snapshot of the live row at the time this version was written
  "agent_role"      varchar(64)  NOT NULL,
  "provider"        varchar(32)  NOT NULL,
  "model"           varchar(128) NOT NULL,
  "base_url"        varchar(256),
  "credential_ref"  varchar(256) NOT NULL,
  "system_prompt"   text,
  "options"         jsonb,
  "enabled"         boolean      NOT NULL,
  "notes"           text,
  "display_name"    varchar(160) NOT NULL,
  "description"     text,

  -- Provenance
  "change_action"      varchar(32) NOT NULL
    CHECK ("change_action" IN ('initial', 'create', 'update', 'rollback')),
  "change_reason"      text,
  "changed_fields"     text[],     -- which fields differ from the prior version (NULL on 'initial')
  "rolled_back_from_version_id" uuid REFERENCES "llm_config_versions"("id") ON DELETE SET NULL,

  "created_at"           timestamp with time zone NOT NULL DEFAULT now(),
  "created_by_user_id"   uuid REFERENCES "users"("id") ON DELETE SET NULL,

  CONSTRAINT "llm_config_versions_unique_per_config"
    UNIQUE ("llm_config_id", "version_number")
);

CREATE INDEX IF NOT EXISTS "llm_config_versions_lookup_idx"
  ON "llm_config_versions" ("llm_config_id", "version_number" DESC);

CREATE INDEX IF NOT EXISTS "llm_config_versions_tenant_idx"
  ON "llm_config_versions" ("client_id", "created_at" DESC);

-- RLS — same FORCE pattern as Loop 4 Phase 4.3.
ALTER TABLE "llm_config_versions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "llm_config_versions" FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policy WHERE polname = 'llm_config_versions_tenant_isolation'
  ) THEN
    CREATE POLICY "llm_config_versions_tenant_isolation"
      ON "llm_config_versions"
      USING (
        "client_id" = NULLIF(current_setting('app.current_client_id', true), '')::uuid
      )
      WITH CHECK (
        "client_id" = NULLIF(current_setting('app.current_client_id', true), '')::uuid
      );
  END IF;
END$$;

-- iwo3_app gets SELECT + INSERT. No UPDATE / DELETE — rows are immutable.
GRANT SELECT, INSERT ON "llm_config_versions" TO iwo3_app;

-- Backfill: every existing llm_configs row gets version 1 = current state.
-- 'initial' marker so consumers know this row is synthetic, not a real
-- mutation. created_by_user_id NULL = system actor.
INSERT INTO "llm_config_versions" (
  "llm_config_id", "client_id", "version_number",
  "agent_role", "provider", "model", "base_url", "credential_ref", "system_prompt",
  "options", "enabled", "notes", "display_name", "description",
  "change_action", "change_reason", "created_at"
)
SELECT
  c."id", c."client_id", 1,
  c."agent_role", c."provider", c."model", c."base_url", c."credential_ref", c."system_prompt",
  c."options", c."enabled", c."notes", c."display_name", c."description",
  'initial',
  'Beta-2 phase 0.3.1 backfill — pre-versioning snapshot',
  c."created_at"
FROM "llm_configs" c
ON CONFLICT ("llm_config_id", "version_number") DO NOTHING;
