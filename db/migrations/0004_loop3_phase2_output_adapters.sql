CREATE TYPE "public"."adapter_policy_mode" AS ENUM('none', 'approval_required', 'disallowed');--> statement-breakpoint
CREATE TYPE "public"."adapter_catalog_status" AS ENUM('active', 'beta', 'deprecated');--> statement-breakpoint
CREATE TYPE "public"."adapter_category" AS ENUM('design_render', 'storage', 'campaign', 'crm', 'other');--> statement-breakpoint
CREATE TYPE "public"."adapter_credential_status" AS ENUM('active', 'rotation_due', 'revoked', 'expired');--> statement-breakpoint
CREATE TYPE "public"."client_adapter_config_status" AS ENUM('active', 'paused', 'revoked');--> statement-breakpoint
CREATE TYPE "public"."external_execution_result_status" AS ENUM('success', 'partial', 'failed', 'unknown');--> statement-breakpoint
CREATE TYPE "public"."output_handoff_candidate_status" AS ENUM('not_candidate', 'candidate', 'selected', 'rejected', 'finalized');--> statement-breakpoint
CREATE TYPE "public"."output_handoff_status" AS ENUM('queued', 'submitted', 'accepted', 'completed', 'failed', 'cancelled');--> statement-breakpoint
CREATE TYPE "public"."output_package_status" AS ENUM('draft', 'validated', 'rejected', 'submitted', 'delivered', 'failed', 'cancelled');--> statement-breakpoint
CREATE TYPE "public"."output_package_kind" AS ENUM('gamma_pptx', 'gamma_pdf', 'sandbox_pptx', 'sandbox_pdf', 'email_campaign', 'drive_upload', 'crm_mutation', 'figma_handoff', 'stitch_handoff', 'designlab_handoff', 'generic');--> statement-breakpoint
CREATE TABLE "adapter_action_policies" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"adapter_catalog_id" uuid NOT NULL,
	"action_key" varchar(64) NOT NULL,
	"mode" "adapter_policy_mode" NOT NULL,
	"reason" text,
	"metadata" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "adapter_action_policies_cfg_action_uniq" UNIQUE("client_id","adapter_catalog_id","action_key")
);
--> statement-breakpoint
CREATE TABLE "adapter_actions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"adapter_catalog_id" uuid NOT NULL,
	"action_key" varchar(64) NOT NULL,
	"display_name" varchar(128) NOT NULL,
	"description" text,
	"requires_output_package" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "adapter_actions_catalog_action_uniq" UNIQUE("adapter_catalog_id","action_key")
);
--> statement-breakpoint
CREATE TABLE "adapter_catalog" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"adapter_key" varchar(64) NOT NULL,
	"display_name" varchar(128) NOT NULL,
	"category" "adapter_category" NOT NULL,
	"description" text,
	"contract_version" varchar(32) DEFAULT 'v0' NOT NULL,
	"status" "adapter_catalog_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "adapter_catalog_adapter_key_unique" UNIQUE("adapter_key")
);
--> statement-breakpoint
CREATE TABLE "adapter_credentials" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"adapter_catalog_id" uuid NOT NULL,
	"credential_ref" varchar(256) NOT NULL,
	"scope" jsonb,
	"rotation_due_at" timestamp with time zone,
	"status" "adapter_credential_status" DEFAULT 'active' NOT NULL,
	"metadata" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "client_adapter_configs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"adapter_catalog_id" uuid NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"credential_ref" varchar(256),
	"config" jsonb,
	"status" "client_adapter_config_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "client_adapter_configs_client_adapter_uniq" UNIQUE("client_id","adapter_catalog_id")
);
--> statement-breakpoint
CREATE TABLE "external_execution_results" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"output_handoff_id" uuid NOT NULL,
	"status" "external_execution_result_status" NOT NULL,
	"received_at" timestamp with time zone DEFAULT now() NOT NULL,
	"payload_ref" varchar(1024),
	"error_message" text,
	"metadata" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "output_handoffs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"deployment_id" uuid,
	"work_order_id" uuid,
	"workflow_id" uuid,
	"execution_cycle_id" uuid,
	"output_package_id" uuid,
	"adapter_catalog_id" uuid,
	"template_profile_id" uuid,
	"external_destination" varchar(256),
	"external_reference" varchar(256),
	"status" "output_handoff_status" DEFAULT 'queued' NOT NULL,
	"handoff_payload_ref" varchar(1024),
	"result_payload_ref" varchar(1024),
	"correlation_id" varchar(128),
	"candidate_group_id" uuid,
	"candidate_status" "output_handoff_candidate_status" DEFAULT 'not_candidate' NOT NULL,
	"selected_at" timestamp with time zone,
	"selected_by_user_id" uuid,
	"metadata" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "output_packages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"schema_version" varchar(16) DEFAULT 'v0' NOT NULL,
	"client_id" uuid NOT NULL,
	"work_order_id" uuid,
	"workflow_execution_id" uuid,
	"output_kind" "output_package_kind" NOT NULL,
	"title" varchar(512) NOT NULL,
	"summary" text,
	"status" "output_package_status" DEFAULT 'draft' NOT NULL,
	"priority" "work_order_priority" DEFAULT 'medium' NOT NULL,
	"content_blocks" jsonb NOT NULL,
	"asset_refs" jsonb,
	"template_profile_id" uuid,
	"render_policy" jsonb,
	"destination_targets" jsonb,
	"approval_policy" jsonb,
	"compliance_notes" text,
	"provenance" jsonb,
	"correlation_id" varchar(128),
	"created_by_user_id" uuid,
	"due_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "adapter_action_policies" ADD CONSTRAINT "adapter_action_policies_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "adapter_action_policies" ADD CONSTRAINT "adapter_action_policies_adapter_catalog_id_adapter_catalog_id_fk" FOREIGN KEY ("adapter_catalog_id") REFERENCES "public"."adapter_catalog"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "adapter_actions" ADD CONSTRAINT "adapter_actions_adapter_catalog_id_adapter_catalog_id_fk" FOREIGN KEY ("adapter_catalog_id") REFERENCES "public"."adapter_catalog"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "adapter_credentials" ADD CONSTRAINT "adapter_credentials_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "adapter_credentials" ADD CONSTRAINT "adapter_credentials_adapter_catalog_id_adapter_catalog_id_fk" FOREIGN KEY ("adapter_catalog_id") REFERENCES "public"."adapter_catalog"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "client_adapter_configs" ADD CONSTRAINT "client_adapter_configs_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "client_adapter_configs" ADD CONSTRAINT "client_adapter_configs_adapter_catalog_id_adapter_catalog_id_fk" FOREIGN KEY ("adapter_catalog_id") REFERENCES "public"."adapter_catalog"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "external_execution_results" ADD CONSTRAINT "external_execution_results_output_handoff_id_output_handoffs_id_fk" FOREIGN KEY ("output_handoff_id") REFERENCES "public"."output_handoffs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD CONSTRAINT "output_handoffs_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD CONSTRAINT "output_handoffs_work_order_id_work_orders_id_fk" FOREIGN KEY ("work_order_id") REFERENCES "public"."work_orders"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD CONSTRAINT "output_handoffs_workflow_id_workflows_id_fk" FOREIGN KEY ("workflow_id") REFERENCES "public"."workflows"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD CONSTRAINT "output_handoffs_execution_cycle_id_execution_cycles_id_fk" FOREIGN KEY ("execution_cycle_id") REFERENCES "public"."execution_cycles"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD CONSTRAINT "output_handoffs_output_package_id_output_packages_id_fk" FOREIGN KEY ("output_package_id") REFERENCES "public"."output_packages"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD CONSTRAINT "output_handoffs_adapter_catalog_id_adapter_catalog_id_fk" FOREIGN KEY ("adapter_catalog_id") REFERENCES "public"."adapter_catalog"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD CONSTRAINT "output_handoffs_template_profile_id_template_profiles_id_fk" FOREIGN KEY ("template_profile_id") REFERENCES "public"."template_profiles"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD CONSTRAINT "output_handoffs_selected_by_user_id_users_id_fk" FOREIGN KEY ("selected_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_packages" ADD CONSTRAINT "output_packages_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_packages" ADD CONSTRAINT "output_packages_work_order_id_work_orders_id_fk" FOREIGN KEY ("work_order_id") REFERENCES "public"."work_orders"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_packages" ADD CONSTRAINT "output_packages_workflow_execution_id_workflow_executions_id_fk" FOREIGN KEY ("workflow_execution_id") REFERENCES "public"."workflow_executions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_packages" ADD CONSTRAINT "output_packages_template_profile_id_template_profiles_id_fk" FOREIGN KEY ("template_profile_id") REFERENCES "public"."template_profiles"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "output_packages" ADD CONSTRAINT "output_packages_created_by_user_id_users_id_fk" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "output_handoffs_client_status_created_idx" ON "output_handoffs" USING btree ("client_id","status","created_at");--> statement-breakpoint
CREATE INDEX "output_handoffs_candidate_group_idx" ON "output_handoffs" USING btree ("candidate_group_id");--> statement-breakpoint
CREATE INDEX "output_packages_client_status_created_idx" ON "output_packages" USING btree ("client_id","status","created_at");