CREATE TYPE "public"."execution_cycle_trigger" AS ENUM('new', 'retry', 'reopen', 'unblock', 'watchdog', 'admin_repair', 'candidate_request_more');--> statement-breakpoint
CREATE TYPE "public"."work_order_priority" AS ENUM('low', 'medium', 'high', 'critical');--> statement-breakpoint
CREATE TYPE "public"."work_order_status" AS ENUM('pending', 'processing', 'blocked', 'awaiting_operator', 'completed', 'done', 'failed', 'deferred', 'cancelled');--> statement-breakpoint
CREATE TYPE "public"."workflow_status" AS ENUM('active', 'paused', 'archived');--> statement-breakpoint
CREATE TYPE "public"."workflow_template_status" AS ENUM('draft', 'published', 'deprecated');--> statement-breakpoint
CREATE TYPE "public"."workflow_execution_status" AS ENUM('pending', 'running', 'completed', 'failed', 'cancelled');--> statement-breakpoint
CREATE TYPE "public"."workflow_step_run_status" AS ENUM('pending', 'running', 'completed', 'failed', 'skipped');--> statement-breakpoint
CREATE TABLE "execution_cycles" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"work_order_id" uuid NOT NULL,
	"cycle_number" integer NOT NULL,
	"trigger" "execution_cycle_trigger" NOT NULL,
	"initiated_by_user_id" uuid,
	"reason" text,
	"prior_cycle_id" uuid,
	"started_at" timestamp with time zone DEFAULT now() NOT NULL,
	"completed_at" timestamp with time zone,
	"terminal_status" varchar(64),
	"metadata" jsonb,
	CONSTRAINT "execution_cycles_wo_cycle_uniq" UNIQUE("work_order_id","cycle_number")
);
--> statement-breakpoint
CREATE TABLE "work_orders" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"title" varchar(512) NOT NULL,
	"description" text,
	"type" varchar(64) DEFAULT 'standard' NOT NULL,
	"priority" "work_order_priority" DEFAULT 'medium' NOT NULL,
	"status" "work_order_status" DEFAULT 'pending' NOT NULL,
	"submitted_by_user_id" uuid,
	"correlation_id" varchar(128),
	"gcc_memory" jsonb,
	"deferred_until" timestamp with time zone,
	"deferred_reason" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "workflows" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"key" varchar(128) NOT NULL,
	"display_name" varchar(256) NOT NULL,
	"description" text,
	"status" "workflow_status" DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "workflows_client_key_uniq" UNIQUE("client_id","key")
);
--> statement-breakpoint
CREATE TABLE "workflow_templates" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workflow_id" uuid NOT NULL,
	"version" varchar(32) NOT NULL,
	"description" text,
	"config" jsonb,
	"status" "workflow_template_status" DEFAULT 'draft' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"published_at" timestamp with time zone,
	CONSTRAINT "workflow_templates_workflow_version_uniq" UNIQUE("workflow_id","version")
);
--> statement-breakpoint
CREATE TABLE "workflow_template_steps" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"template_id" uuid NOT NULL,
	"step_key" varchar(128) NOT NULL,
	"step_order" integer NOT NULL,
	"display_name" varchar(256) NOT NULL,
	"assigned_sub_agent_key" varchar(64),
	"prompt_ref" jsonb,
	"retry_policy" jsonb,
	"timeout_ms" integer,
	"tool_ids" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "workflow_template_steps_template_key_uniq" UNIQUE("template_id","step_key"),
	CONSTRAINT "workflow_template_steps_template_order_uniq" UNIQUE("template_id","step_order")
);
--> statement-breakpoint
CREATE TABLE "workflow_executions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"template_id" uuid NOT NULL,
	"work_order_id" uuid,
	"status" "workflow_execution_status" DEFAULT 'pending' NOT NULL,
	"current_step_key" varchar(128),
	"goal" text,
	"final_work_product" jsonb,
	"executive_review" jsonb,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "workflow_step_runs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"execution_id" uuid NOT NULL,
	"step_key" varchar(128) NOT NULL,
	"step_order" integer NOT NULL,
	"status" "workflow_step_run_status" DEFAULT 'pending' NOT NULL,
	"input" jsonb,
	"output" jsonb,
	"pm_review" jsonb,
	"revision_attempt" integer DEFAULT 0 NOT NULL,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "workflow_step_runs_execution_step_uniq" UNIQUE("execution_id","step_key")
);
--> statement-breakpoint
-- NOTE: drizzle-kit emitted an ALTER TABLE action_audit_log ADD PRIMARY KEY
-- (id, created_at) here. That PK was already set by Phase 1.5 migration
-- `0002_partition_action_audit_log.sql` (which replaces the table with a
-- partitioned version keyed on the same composite PK). Re-adding it fails
-- with "multiple primary keys for table". Removed manually.
--> statement-breakpoint

ALTER TABLE "execution_cycles" ADD CONSTRAINT "execution_cycles_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "execution_cycles" ADD CONSTRAINT "execution_cycles_work_order_id_work_orders_id_fk" FOREIGN KEY ("work_order_id") REFERENCES "public"."work_orders"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "execution_cycles" ADD CONSTRAINT "execution_cycles_initiated_by_user_id_users_id_fk" FOREIGN KEY ("initiated_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "execution_cycles" ADD CONSTRAINT "execution_cycles_prior_cycle_id_execution_cycles_id_fk" FOREIGN KEY ("prior_cycle_id") REFERENCES "public"."execution_cycles"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "work_orders" ADD CONSTRAINT "work_orders_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "work_orders" ADD CONSTRAINT "work_orders_submitted_by_user_id_users_id_fk" FOREIGN KEY ("submitted_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflows" ADD CONSTRAINT "workflows_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflow_templates" ADD CONSTRAINT "workflow_templates_workflow_id_workflows_id_fk" FOREIGN KEY ("workflow_id") REFERENCES "public"."workflows"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflow_template_steps" ADD CONSTRAINT "workflow_template_steps_template_id_workflow_templates_id_fk" FOREIGN KEY ("template_id") REFERENCES "public"."workflow_templates"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflow_executions" ADD CONSTRAINT "workflow_executions_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflow_executions" ADD CONSTRAINT "workflow_executions_template_id_workflow_templates_id_fk" FOREIGN KEY ("template_id") REFERENCES "public"."workflow_templates"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflow_executions" ADD CONSTRAINT "workflow_executions_work_order_id_work_orders_id_fk" FOREIGN KEY ("work_order_id") REFERENCES "public"."work_orders"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflow_step_runs" ADD CONSTRAINT "workflow_step_runs_execution_id_workflow_executions_id_fk" FOREIGN KEY ("execution_id") REFERENCES "public"."workflow_executions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "execution_cycles_client_started_idx" ON "execution_cycles" USING btree ("client_id","started_at");--> statement-breakpoint
CREATE INDEX "work_orders_client_status_created_idx" ON "work_orders" USING btree ("client_id","status","created_at");--> statement-breakpoint
CREATE INDEX "workflow_executions_client_status_created_idx" ON "workflow_executions" USING btree ("client_id","status","created_at");