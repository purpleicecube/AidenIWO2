import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { workflows } from "./workflows";

export const workflowTemplateStatusEnum = pgEnum("workflow_template_status", [
  "draft",
  "published",
  "deprecated",
]);

/**
 * Workflow template version — the concrete recipe for a given workflow
 * at a given version. `config` carries template-level settings that do
 * not belong on individual steps (e.g. category, preferred PM,
 * gammaDeliveryPolicy, default render route). Steps live in
 * `workflow_template_steps` and reference this row.
 */
export const workflowTemplates = pgTable(
  "workflow_templates",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    workflowId: uuid("workflow_id")
      .notNull()
      .references(() => workflows.id, { onDelete: "restrict" }),
    version: varchar("version", { length: 32 }).notNull(),
    description: text("description"),
    config: jsonb("config"),
    status: workflowTemplateStatusEnum("status").notNull().default("draft"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    publishedAt: timestamp("published_at", { withTimezone: true }),
  },
  (t) => ({
    uniqWorkflowVersion: unique("workflow_templates_workflow_version_uniq").on(
      t.workflowId,
      t.version
    ),
  })
);

export type WorkflowTemplate = typeof workflowTemplates.$inferSelect;
export type NewWorkflowTemplate = typeof workflowTemplates.$inferInsert;
