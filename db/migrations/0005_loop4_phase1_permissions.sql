-- Loop 4 Phase 1 — RBAC permission vocabulary, role mapping, per-user overrides.
-- See ADR-014 (RBAC permission model) and IWO3_LOOP_4_APPROVAL_DECISIONS §Q1/§Q2.
-- Note: drizzle-kit re-emitted `CREATE TYPE output_package_kind` plus a matching
-- `ALTER TABLE output_packages ALTER COLUMN output_kind` due to meta snapshot
-- drift (Risk D08). Both were stripped here because Phase 3.2 already landed
-- them in 0004_loop3_phase2_output_adapters.sql. Drift remains contained to
-- the meta snapshot (0005_snapshot.json); the actual DB schema is correct.
CREATE TYPE "public"."permission_scope" AS ENUM('global', 'tenant', 'resource');--> statement-breakpoint
CREATE TYPE "public"."permission_grant_type" AS ENUM('allow', 'deny');--> statement-breakpoint
CREATE TABLE "permissions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"permission_key" varchar(96) NOT NULL,
	"display_name" varchar(160) NOT NULL,
	"description" text,
	"scope" "permission_scope" NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "permissions_permission_key_unique" UNIQUE("permission_key")
);
--> statement-breakpoint
CREATE TABLE "role_permissions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"role" "membership_role" NOT NULL,
	"permission_id" uuid NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "role_permissions_role_permission_uniq" UNIQUE("role","permission_id")
);
--> statement-breakpoint
CREATE TABLE "permission_grants" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"client_id" uuid NOT NULL,
	"permission_id" uuid NOT NULL,
	"grant_type" "permission_grant_type" NOT NULL,
	"granted_by_user_id" uuid,
	"reason" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "permission_grants_user_client_permission_uniq" UNIQUE("user_id","client_id","permission_id")
);
--> statement-breakpoint
ALTER TABLE "role_permissions" ADD CONSTRAINT "role_permissions_permission_id_permissions_id_fk" FOREIGN KEY ("permission_id") REFERENCES "public"."permissions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "permission_grants" ADD CONSTRAINT "permission_grants_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "permission_grants" ADD CONSTRAINT "permission_grants_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "permission_grants" ADD CONSTRAINT "permission_grants_permission_id_permissions_id_fk" FOREIGN KEY ("permission_id") REFERENCES "public"."permissions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "permission_grants" ADD CONSTRAINT "permission_grants_granted_by_user_id_users_id_fk" FOREIGN KEY ("granted_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;