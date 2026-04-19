CREATE TYPE "public"."membership_role" AS ENUM('owner', 'admin', 'operator', 'reviewer', 'viewer', 'agent_system');--> statement-breakpoint
CREATE TYPE "public"."membership_status" AS ENUM('active', 'revoked');--> statement-breakpoint
CREATE TYPE "public"."client_status" AS ENUM('active', 'suspended');--> statement-breakpoint
CREATE TYPE "public"."deployment_mode" AS ENUM('dedicated_single_client', 'shared_multi_tenant', 'hybrid');--> statement-breakpoint
CREATE TYPE "public"."user_status" AS ENUM('active', 'disabled');--> statement-breakpoint
CREATE TYPE "public"."fallback_policy" AS ENUM('none', 'allowed_with_approval', 'allowed');--> statement-breakpoint
CREATE TYPE "public"."output_kind" AS ENUM('pptx', 'pdf', 'other');--> statement-breakpoint
CREATE TYPE "public"."render_engine" AS ENUM('gamma', 'gamma_basic', 'sandbox_pptx', 'sandbox_pdf', 'designlab');--> statement-breakpoint
CREATE TYPE "public"."template_profile_status" AS ENUM('active', 'archived');--> statement-breakpoint
CREATE TYPE "public"."manifest_owner" AS ENUM('drizzle', 'alembic');--> statement-breakpoint
CREATE TYPE "public"."manifest_source" AS ENUM('iwo2_parity', 'iwo3_native');--> statement-breakpoint
CREATE TABLE "client_memberships" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"role" "membership_role" NOT NULL,
	"status" "membership_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "client_memberships_client_user_uniq" UNIQUE("client_id","user_id")
);
--> statement-breakpoint
CREATE TABLE "clients" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"designation" varchar(128) NOT NULL,
	"display_name" varchar(256) NOT NULL,
	"deployment_mode" "deployment_mode" NOT NULL,
	"status" "client_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "clients_designation_unique" UNIQUE("designation")
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"email" varchar(320) NOT NULL,
	"display_name" varchar(256) NOT NULL,
	"status" "user_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "users_email_unique" UNIQUE("email")
);
--> statement-breakpoint
CREATE TABLE "template_profiles" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"profile_key" varchar(128) NOT NULL,
	"output_kind" "output_kind" NOT NULL,
	"engine" "render_engine" NOT NULL,
	"external_ref" varchar(256),
	"fidelity_required" boolean DEFAULT true NOT NULL,
	"fallback_policy" "fallback_policy" DEFAULT 'none' NOT NULL,
	"content_contract" jsonb,
	"status" "template_profile_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "template_profiles_client_key_uniq" UNIQUE("client_id","profile_key")
);
--> statement-breakpoint
CREATE TABLE "migration_source_manifest" (
	"table_name" varchar(128) PRIMARY KEY NOT NULL,
	"source" "manifest_source" NOT NULL,
	"source_version" varchar(64) NOT NULL,
	"owned_by" "manifest_owner" NOT NULL,
	"introduced_at" timestamp with time zone DEFAULT now() NOT NULL,
	"notes" text
);
--> statement-breakpoint
ALTER TABLE "client_memberships" ADD CONSTRAINT "client_memberships_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "client_memberships" ADD CONSTRAINT "client_memberships_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "template_profiles" ADD CONSTRAINT "template_profiles_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;