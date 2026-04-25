-- Loop 9 Phase 9.3 — LLM Foundation: per-tenant per-role provider config.
-- See ADR-021 (LLM provider abstraction + config resolution).
-- Renamed from drizzle-kit's emitted 0006_busy_squadron_sinister so the
-- file order matches the migration index (0007 = Phase 9.1 credential
-- gating; 0008 = Phase 9.3 LLM Foundation).
-- RLS attached at the bottom: same iwo3_app + app.current_client_id
-- pattern as adapter_credentials / permissions / etc (see Loop 4 Phase
-- 4.3 raw-SQL migration 0006_rls_tenant_isolation.sql for the lineage).
CREATE TABLE "llm_configs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"agent_role" varchar(64) NOT NULL,
	"provider" varchar(32) NOT NULL,
	"model" varchar(128) NOT NULL,
	"base_url" varchar(256),
	"credential_ref" varchar(256) NOT NULL,
	"system_prompt" text,
	"options" jsonb,
	"enabled" boolean DEFAULT true NOT NULL,
	"notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "llm_configs_client_role_uniq" UNIQUE("client_id","agent_role")
);
--> statement-breakpoint
ALTER TABLE "llm_configs" ADD CONSTRAINT "llm_configs_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "llm_configs" ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE "llm_configs" FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY "llm_configs_tenant_isolation" ON "llm_configs"
  FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint
GRANT SELECT, INSERT, UPDATE, DELETE ON "llm_configs" TO iwo3_app;
