-- Pre-Beta Loop δ.1 — Workspace folder tree.
-- See db/schema/workspace_folders.ts and
-- IWO3_PRE_BETA_PRODUCT_SURFACE_REMEDIATION_PRESTART_QUESTIONS_v0.1.0.md
-- § Workspace storage substrate (architect decision: B).

CREATE TABLE "workspace_folders" (
  "id"                 uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "client_id"          uuid NOT NULL,
  "parent_folder_id"   uuid,
  "name"               varchar(256) NOT NULL,
  "created_by_user_id" uuid NOT NULL,
  "created_at"         timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at"         timestamp with time zone DEFAULT now() NOT NULL,
  "deleted_at"         timestamp with time zone,
  CONSTRAINT "workspace_folders_sibling_name_uniq"
    UNIQUE ("client_id", "parent_folder_id", "name")
);
--> statement-breakpoint

ALTER TABLE "workspace_folders"
  ADD CONSTRAINT "workspace_folders_client_id_clients_id_fk"
  FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id")
  ON DELETE restrict ON UPDATE no action;
--> statement-breakpoint

ALTER TABLE "workspace_folders"
  ADD CONSTRAINT "workspace_folders_parent_folder_id_workspace_folders_id_fk"
  FOREIGN KEY ("parent_folder_id") REFERENCES "public"."workspace_folders"("id")
  ON DELETE restrict ON UPDATE no action;
--> statement-breakpoint

ALTER TABLE "workspace_folders"
  ADD CONSTRAINT "workspace_folders_created_by_user_id_users_id_fk"
  FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id")
  ON DELETE restrict ON UPDATE no action;
--> statement-breakpoint

CREATE INDEX "workspace_folders_client_parent_idx"
  ON "workspace_folders" ("client_id", "parent_folder_id");
--> statement-breakpoint

-- RLS posture mirrors artifacts (see migration 0006 § artifacts).
ALTER TABLE "workspace_folders" ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE "workspace_folders" FORCE ROW LEVEL SECURITY;
--> statement-breakpoint

CREATE POLICY "workspace_folders_tenant_iso" ON "workspace_folders" FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

-- Existing iwo3_app role already has table-level ALL via DEFAULT PRIVILEGES
-- in migration 0006. Confirm explicit grant for clarity.
GRANT SELECT, INSERT, UPDATE, DELETE ON "workspace_folders" TO iwo3_app;
--> statement-breakpoint

-- Extend artifacts with workspace_folder_id (nullable; legacy rows + tenant-wide
-- artifacts that aren't yet placed in the tree stay valid).
ALTER TABLE "artifacts"
  ADD COLUMN IF NOT EXISTS "workspace_folder_id" uuid;
--> statement-breakpoint

ALTER TABLE "artifacts"
  ADD CONSTRAINT "artifacts_workspace_folder_id_workspace_folders_id_fk"
  FOREIGN KEY ("workspace_folder_id")
  REFERENCES "public"."workspace_folders"("id")
  ON DELETE set null ON UPDATE no action;
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "artifacts_workspace_folder_idx"
  ON "artifacts" ("workspace_folder_id");
--> statement-breakpoint

-- Tenant root + Outputs folder. Idempotent on the sibling-name UNIQUE so
-- reruns are safe. Each tenant gets:
--   "/"        the tenant root (parent_folder_id IS NULL)
--   "Outputs"  the auto-save destination for produce_output_package
-- Both are owned by the tenant's first agent_system user (worker-style).
INSERT INTO workspace_folders (id, client_id, parent_folder_id, name, created_by_user_id)
SELECT
  gen_random_uuid(),
  c.id,
  NULL,
  '/',
  (SELECT u.id FROM users u
     JOIN client_memberships m ON m.user_id = u.id
                              AND m.client_id = c.id
                              AND m.role = 'agent_system'
                              AND m.status = 'active'
                              AND u.status = 'active'
    ORDER BY u.created_at ASC
    LIMIT 1)
FROM clients c
WHERE c.status = 'active'::client_status
  AND EXISTS (SELECT 1 FROM users u
                JOIN client_memberships m ON m.user_id = u.id
                                         AND m.client_id = c.id
                                         AND m.role = 'agent_system'
                                         AND m.status = 'active')
ON CONFLICT ON CONSTRAINT workspace_folders_sibling_name_uniq DO NOTHING;
--> statement-breakpoint

INSERT INTO workspace_folders (id, client_id, parent_folder_id, name, created_by_user_id)
SELECT
  gen_random_uuid(),
  c.id,
  root.id,
  'Outputs',
  root.created_by_user_id
FROM clients c
JOIN workspace_folders root ON root.client_id = c.id
                           AND root.parent_folder_id IS NULL
                           AND root.name = '/'
                           AND root.deleted_at IS NULL
WHERE c.status = 'active'::client_status
ON CONFLICT ON CONSTRAINT workspace_folders_sibling_name_uniq DO NOTHING;
