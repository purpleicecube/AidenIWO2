import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  timestamp,
  pgEnum,
  index,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";
import { workOrders } from "./work_orders";
import { workflowExecutions } from "./workflow_executions";
import { templateProfiles } from "./template_profiles";
import { workOrderPriorityEnum } from "./work_orders";

export const outputPackageStatusEnum = pgEnum("output_package_status", [
  "draft",
  "validated",
  "rejected",
  "submitted",
  "delivered",
  "failed",
  "cancelled",
]);

// Note: enum DB name is `output_package_kind` to avoid a clash with the
// existing `output_kind` enum that Loop 1 created for `template_profiles`.
// The column is still named `output_kind` on `output_packages`.
//
// Loop CAP-A Φ.0b — broadened with six new concrete delivery-target
// kinds for sandbox-local HTML / DOCX / MD renders and the three
// design-input HTML render lanes (Stitch / Figma / 21st-Magic).
// Migration 0030.
export const outputPackageKindEnum = pgEnum("output_package_kind", [
  "gamma_pptx",
  "gamma_pdf",
  "sandbox_pptx",
  "sandbox_pdf",
  "email_campaign",
  "drive_upload",
  "crm_mutation",
  "figma_handoff",
  "stitch_handoff",
  "designlab_handoff",
  "generic",
  "sandbox_html",
  "sandbox_docx",
  "sandbox_md",
  "stitch_html_render",
  "figma_html_render",
  "twentyfirst_html_render",
]);

/**
 * OutputPackage — typed envelope per CODEX §1 that carries a Work Order
 * or Workflow execution's deliverable toward one or more adapters.
 * `content_blocks` holds the kind-specific payload (e.g. a Gamma render
 * spec, an email-campaign spec, a Drive upload manifest). The
 * adapter-side consumers switch on `output_kind` to interpret
 * `content_blocks`.
 *
 * Tenant-scoped via `client_id`. Source-of-execution is captured by
 * whichever of `work_order_id` / `workflow_execution_id` is populated
 * (at least one must be NOT NULL — enforced by a check constraint in
 * the raw-SQL migration).
 */
export const outputPackages = pgTable(
  "output_packages",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    schemaVersion: varchar("schema_version", { length: 16 })
      .notNull()
      .default("v0"),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    workOrderId: uuid("work_order_id").references(() => workOrders.id, {
      onDelete: "set null",
    }),
    workflowExecutionId: uuid("workflow_execution_id").references(
      () => workflowExecutions.id,
      { onDelete: "set null" }
    ),
    outputKind: outputPackageKindEnum("output_kind").notNull(),
    title: varchar("title", { length: 512 }).notNull(),
    summary: text("summary"),
    status: outputPackageStatusEnum("status").notNull().default("draft"),
    priority: workOrderPriorityEnum("priority").notNull().default("medium"),
    contentBlocks: jsonb("content_blocks").notNull(),
    assetRefs: jsonb("asset_refs"),
    templateProfileId: uuid("template_profile_id").references(
      () => templateProfiles.id,
      { onDelete: "set null" }
    ),
    renderPolicy: jsonb("render_policy"),
    destinationTargets: jsonb("destination_targets"),
    approvalPolicy: jsonb("approval_policy"),
    complianceNotes: text("compliance_notes"),
    provenance: jsonb("provenance"),
    correlationId: varchar("correlation_id", { length: 128 }),
    createdByUserId: uuid("created_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    dueAt: timestamp("due_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    idxClientStatusCreated: index("output_packages_client_status_created_idx").on(
      t.clientId,
      t.status,
      t.createdAt
    ),
  })
);

export type OutputPackage = typeof outputPackages.$inferSelect;
export type NewOutputPackage = typeof outputPackages.$inferInsert;
