CREATE TYPE "public"."channel_auth_code_status" AS ENUM('pending', 'consumed', 'expired', 'revoked');--> statement-breakpoint
CREATE TYPE "public"."channel_identity_status" AS ENUM('active', 'revoked');--> statement-breakpoint
CREATE TYPE "public"."channel_kind" AS ENUM('telegram', 'slack', 'email', 'sms');--> statement-breakpoint
CREATE TYPE "public"."channel_message_direction" AS ENUM('inbound', 'outbound');--> statement-breakpoint
CREATE TYPE "public"."channel_message_status" AS ENUM('received', 'processed', 'failed', 'pending', 'sent');--> statement-breakpoint
CREATE TABLE "channel_auth_codes" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"code" varchar(64) NOT NULL,
	"channel_kind" "channel_kind" NOT NULL,
	"issued_by_user_id" uuid NOT NULL,
	"status" "channel_auth_code_status" DEFAULT 'pending' NOT NULL,
	"consumed_external_id" varchar(256),
	"expires_at" timestamp with time zone NOT NULL,
	"consumed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "channel_auth_codes_code_uniq" UNIQUE("code")
);
--> statement-breakpoint
CREATE TABLE "channel_identities" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"channel_kind" "channel_kind" NOT NULL,
	"external_id" varchar(256) NOT NULL,
	"user_id" uuid NOT NULL,
	"status" "channel_identity_status" DEFAULT 'active' NOT NULL,
	"metadata" jsonb,
	"bound_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_seen_at" timestamp with time zone,
	"revoked_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "channel_identities_client_channel_external_uniq" UNIQUE("client_id","channel_kind","external_id")
);
--> statement-breakpoint
CREATE TABLE "channel_messages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"client_id" uuid NOT NULL,
	"channel_kind" "channel_kind" NOT NULL,
	"direction" "channel_message_direction" NOT NULL,
	"channel_identity_id" uuid,
	"external_message_id" varchar(256),
	"external_chat_id" varchar(256),
	"idempotency_key" varchar(256),
	"payload" jsonb NOT NULL,
	"intent" varchar(64),
	"related_work_order_id" uuid,
	"related_workflow_execution_id" uuid,
	"status" "channel_message_status" DEFAULT 'received' NOT NULL,
	"attempts" integer DEFAULT 0 NOT NULL,
	"error_detail" text,
	"correlation_id" varchar(128),
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"sent_at" timestamp with time zone,
	"processed_at" timestamp with time zone,
	CONSTRAINT "channel_messages_inbound_external_uniq" UNIQUE("channel_kind","external_message_id"),
	CONSTRAINT "channel_messages_idempotency_uniq" UNIQUE("channel_kind","idempotency_key")
);
--> statement-breakpoint
ALTER TABLE "channel_auth_codes" ADD CONSTRAINT "channel_auth_codes_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "channel_auth_codes" ADD CONSTRAINT "channel_auth_codes_issued_by_user_id_users_id_fk" FOREIGN KEY ("issued_by_user_id") REFERENCES "public"."users"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "channel_identities" ADD CONSTRAINT "channel_identities_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "channel_identities" ADD CONSTRAINT "channel_identities_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "channel_messages" ADD CONSTRAINT "channel_messages_client_id_clients_id_fk" FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "channel_messages" ADD CONSTRAINT "channel_messages_channel_identity_id_channel_identities_id_fk" FOREIGN KEY ("channel_identity_id") REFERENCES "public"."channel_identities"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "channel_messages" ADD CONSTRAINT "channel_messages_related_work_order_id_work_orders_id_fk" FOREIGN KEY ("related_work_order_id") REFERENCES "public"."work_orders"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "channel_messages" ADD CONSTRAINT "channel_messages_related_workflow_execution_id_workflow_executions_id_fk" FOREIGN KEY ("related_workflow_execution_id") REFERENCES "public"."workflow_executions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "channel_identities_channel_external_idx" ON "channel_identities" USING btree ("channel_kind","external_id");--> statement-breakpoint
CREATE INDEX "channel_messages_client_status_created_idx" ON "channel_messages" USING btree ("client_id","status","created_at");--> statement-breakpoint
CREATE INDEX "channel_messages_outbox_pending_idx" ON "channel_messages" USING btree ("direction","status","created_at");--> statement-breakpoint
-- MegaLoop Alpha α.5 — Channel layer RLS.
-- Same Loop 4 Phase 4.3 pattern: ENABLE + FORCE + tenant policy +
-- iwo3_app grant. nullif() empty-string guard per ADR-015 D09.
ALTER TABLE "channel_identities" ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE "channel_identities" FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY "channel_identities_tenant_isolation" ON "channel_identities"
  FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint
GRANT SELECT, INSERT, UPDATE, DELETE ON "channel_identities" TO iwo3_app;
--> statement-breakpoint
ALTER TABLE "channel_auth_codes" ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE "channel_auth_codes" FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY "channel_auth_codes_tenant_isolation" ON "channel_auth_codes"
  FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint
GRANT SELECT, INSERT, UPDATE, DELETE ON "channel_auth_codes" TO iwo3_app;
--> statement-breakpoint
ALTER TABLE "channel_messages" ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE "channel_messages" FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY "channel_messages_tenant_isolation" ON "channel_messages"
  FOR ALL
  USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint
GRANT SELECT, INSERT, UPDATE, DELETE ON "channel_messages" TO iwo3_app;
