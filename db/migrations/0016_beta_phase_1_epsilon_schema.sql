-- MegaLoop Beta Phase 1 (ε.1) — Production-posture schema foundation.
-- Architect-locked decisions Q1, Q5, Q7, Q8, Q11.
-- See IWO3_MEGALOOP_BETA_DECISIONS_v0.1.0.md for the verbatim answers.

-- ── Q1: per-tenant LLM per-WO ceiling override ──────────────────────
ALTER TABLE "clients"
  ADD COLUMN IF NOT EXISTS "llm_per_wo_ceiling" integer;
--> statement-breakpoint

-- ── Q7: chat_sessions table for cross-session operator chat persistence ──
CREATE TABLE IF NOT EXISTS "chat_sessions" (
  "id"         uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id"    uuid NOT NULL,
  "client_id"  uuid NOT NULL,
  "messages"   jsonb NOT NULL DEFAULT '[]'::jsonb,
  "context"    jsonb NOT NULL DEFAULT '{}'::jsonb,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT "chat_sessions_user_client_uniq" UNIQUE ("user_id", "client_id")
);
--> statement-breakpoint

ALTER TABLE "chat_sessions"
  ADD CONSTRAINT "chat_sessions_user_id_users_id_fk"
  FOREIGN KEY ("user_id") REFERENCES "public"."users"("id")
  ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint

ALTER TABLE "chat_sessions"
  ADD CONSTRAINT "chat_sessions_client_id_clients_id_fk"
  FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id")
  ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint

-- RLS posture mirrors artifacts (migration 0006).
ALTER TABLE "chat_sessions" ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE "chat_sessions" FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY "chat_sessions_tenant_iso" ON "chat_sessions" FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

GRANT SELECT, INSERT, UPDATE, DELETE ON "chat_sessions" TO iwo3_app;
--> statement-breakpoint

-- ── Q8: server-side WO idempotency for chat-driven creates ──────────
-- Partial UNIQUE index — only chat-prefixed correlations participate.
-- Other correlation_id values (telegram:, dispatch:, manual operator) keep
-- their existing freedom to repeat. Per architect Q8 verbatim.
CREATE UNIQUE INDEX IF NOT EXISTS "work_orders_chat_correlation_uniq"
  ON "work_orders" ("client_id", "correlation_id")
  WHERE "correlation_id" LIKE 'chat:%';
--> statement-breakpoint

-- ── Q11: per-operator scratch subtree marker on workspace_folders ───
ALTER TABLE "workspace_folders"
  ADD COLUMN IF NOT EXISTS "owner_user_id" uuid;
--> statement-breakpoint

ALTER TABLE "workspace_folders"
  ADD CONSTRAINT "workspace_folders_owner_user_id_users_id_fk"
  FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id")
  ON DELETE set null ON UPDATE no action;
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "workspace_folders_owner_user_idx"
  ON "workspace_folders" ("client_id", "owner_user_id")
  WHERE "owner_user_id" IS NOT NULL;
--> statement-breakpoint

-- ── Q5: RBAC granularity for config CRUD ────────────────────────────
INSERT INTO permissions (id, permission_key, display_name, description, scope)
VALUES
  ('00000000-0000-4000-8000-0000a0000076', 'llm_config:write',
   'Edit LLM configs',
   'Create + update llm_configs rows for this tenant (provider, model, system prompt, enabled flag).',
   'tenant'::permission_scope),
  ('00000000-0000-4000-8000-0000a0000077', 'llm_config:delete',
   'Delete LLM configs',
   'Soft-delete or hard-delete llm_configs rows for this tenant.',
   'tenant'::permission_scope)
ON CONFLICT (permission_key) DO UPDATE
  SET display_name = EXCLUDED.display_name,
      description  = EXCLUDED.description;
--> statement-breakpoint

-- Default role mapping per architect decision (C):
--   write  → owner / admin / operator
--   delete → owner / admin
INSERT INTO role_permissions (role, permission_id)
SELECT r.role::membership_role, p.id
  FROM permissions p
  JOIN (VALUES
    ('owner',    'llm_config:write'),
    ('owner',    'llm_config:delete'),
    ('admin',    'llm_config:write'),
    ('admin',    'llm_config:delete'),
    ('operator', 'llm_config:write')
  ) AS r(role, permission_key) ON r.permission_key = p.permission_key
ON CONFLICT ON CONSTRAINT role_permissions_role_permission_uniq DO NOTHING;
