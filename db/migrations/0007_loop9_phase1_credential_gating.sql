-- Loop 9 Phase 9.1 — credential + gating foundation.
-- See IWO3_LOOP_8_3_CODEX_DECISIONS §Q1 (dual first-live-invocation gate)
-- and §Q2 (env-injected credentials; DB stores ref + metadata only).
-- Renamed from drizzle-kit's emitted 0005_messy_ken_ellis.sql to 0007 so
-- it lands after the hand-authored 0006_rls_tenant_isolation.sql (Risk D08).
-- Emitted SQL had no meta-drift re-emits; all six statements are additive.
ALTER TABLE "adapter_actions" ADD COLUMN "poll_timeout_seconds" integer;--> statement-breakpoint
ALTER TABLE "adapter_credentials" ADD COLUMN "first_invocation_confirmed_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "adapter_credentials" ADD COLUMN "first_invocation_confirmed_by_user_id" uuid;--> statement-breakpoint
ALTER TABLE "adapter_credentials" ADD COLUMN "rotated_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "adapter_credentials" ADD COLUMN "notes" text;--> statement-breakpoint
ALTER TABLE "adapter_credentials" ADD CONSTRAINT "adapter_credentials_first_invocation_confirmed_by_user_id_users_id_fk" FOREIGN KEY ("first_invocation_confirmed_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;