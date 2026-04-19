CREATE TYPE "public"."artifact_content_class" AS ENUM('c0', 'c1', 'c2', 'c3');--> statement-breakpoint
CREATE TYPE "public"."artifact_source_type" AS ENUM('upload', 'generated', 'imported');--> statement-breakpoint
CREATE TYPE "public"."data_source_binding_status" AS ENUM('active', 'paused', 'revoked');--> statement-breakpoint
CREATE TYPE "public"."data_source_connector_type" AS ENUM('postgres', 'bigquery', 'snowflake', 'sheets', 'rest_api', 'custom');--> statement-breakpoint
CREATE TYPE "public"."prompt_profile_scope" AS ENUM('client', 'workflow', 'wo');--> statement-breakpoint
CREATE TYPE "public"."prompt_profile_status" AS ENUM('active', 'archived');--> statement-breakpoint
CREATE TYPE "public"."prompt_version_status" AS ENUM('draft', 'published', 'deprecated');--> statement-breakpoint
CREATE TYPE "public"."repository_binding_status" AS ENUM('active', 'paused', 'revoked');--> statement-breakpoint
CREATE TYPE "public"."repository_connector_type" AS ENUM('google_drive', 'dropbox', 'github', 's3', 'local', 'custom');--> statement-breakpoint
CREATE TABLE "action_audit_log" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"client_id" uuid NOT NULL,
	"actor_user_id" uuid,
	"action" varchar(128) NOT NULL,
	"target_type" varchar(64),
	"target_id" varchar(128),
	"metadata" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "artifacts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"source_type" "artifact_source_type" NOT NULL,
	"content_class" "artifact_content_class" NOT NULL,
	"mime_type" varchar(128),
	"filename" varchar(512),
	"storage_ref" varchar(1024) NOT NULL,
	"extracted_text" text,
	"metadata" jsonb,
	"created_by_user_id" uuid NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "data_source_bindings" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"binding_key" varchar(128) NOT NULL,
	"connector_type" "data_source_connector_type" NOT NULL,
	"scope" jsonb,
	"credential_ref" varchar(256),
	"allowed_locations" jsonb,
	"freshness_policy" jsonb,
	"status" "data_source_binding_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "data_source_bindings_client_key_uniq" UNIQUE("client_id","binding_key")
);
--> statement-breakpoint
CREATE TABLE "prompt_profiles" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"profile_key" varchar(128) NOT NULL,
	"display_name" varchar(256) NOT NULL,
	"scope" "prompt_profile_scope" DEFAULT 'client' NOT NULL,
	"status" "prompt_profile_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "prompt_profiles_client_key_uniq" UNIQUE("client_id","profile_key")
);
--> statement-breakpoint
CREATE TABLE "prompt_profile_versions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"profile_id" uuid NOT NULL,
	"version" varchar(32) NOT NULL,
	"base_prompt" text NOT NULL,
	"constraints" jsonb,
	"authored_by_user_id" uuid NOT NULL,
	"status" "prompt_version_status" DEFAULT 'draft' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"published_at" timestamp with time zone,
	CONSTRAINT "prompt_profile_versions_profile_version_uniq" UNIQUE("profile_id","version")
);
--> statement-breakpoint
CREATE TABLE "prompt_rendered_snapshots" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"correlation_id" varchar(128) NOT NULL,
	"layer_ids" jsonb NOT NULL,
	"rendered_text" text NOT NULL,
	"render_hash" varchar(64) NOT NULL,
	"override_ref" jsonb,
	"rendered_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "repository_bindings" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"binding_key" varchar(128) NOT NULL,
	"connector_type" "repository_connector_type" NOT NULL,
	"scope" jsonb,
	"credential_ref" varchar(256),
	"allowed_locations" jsonb,
	"freshness_policy" jsonb,
	"status" "repository_binding_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "repository_bindings_client_key_uniq" UNIQUE("client_id","binding_key")
);
--> statement-breakpoint
ALTER TABLE "action_audit_log" ADD CONSTRAINT "action_audit_log_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "action_audit_log" ADD CONSTRAINT "action_audit_log_actor_user_id_users_id_fk" FOREIGN KEY ("actor_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_created_by_user_id_users_id_fk" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "data_source_bindings" ADD CONSTRAINT "data_source_bindings_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_profiles" ADD CONSTRAINT "prompt_profiles_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_profile_versions" ADD CONSTRAINT "prompt_profile_versions_profile_id_prompt_profiles_id_fk" FOREIGN KEY ("profile_id") REFERENCES "public"."prompt_profiles"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_profile_versions" ADD CONSTRAINT "prompt_profile_versions_authored_by_user_id_users_id_fk" FOREIGN KEY ("authored_by_user_id") REFERENCES "public"."users"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_rendered_snapshots" ADD CONSTRAINT "prompt_rendered_snapshots_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "repository_bindings" ADD CONSTRAINT "repository_bindings_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "action_audit_log_client_created_idx" ON "action_audit_log" USING btree ("client_id","created_at");--> statement-breakpoint
CREATE INDEX "artifacts_client_created_idx" ON "artifacts" USING btree ("client_id","created_at");--> statement-breakpoint
CREATE INDEX "prompt_snapshots_client_corr_idx" ON "prompt_rendered_snapshots" USING btree ("client_id","correlation_id");--> statement-breakpoint
CREATE INDEX "prompt_snapshots_hash_idx" ON "prompt_rendered_snapshots" USING btree ("render_hash");