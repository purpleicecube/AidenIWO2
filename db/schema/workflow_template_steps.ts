import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  integer,
  timestamp,
  unique,
} from "drizzle-orm/pg-core";
import { workflowTemplates } from "./workflow_templates";

/**
 * Ordered step inside a workflow template version. `prompt_ref` is a
 * loose JSON that the Loop 2 prompt resolver will learn to consume
 * (e.g. `{ kind: "client_profile", profile_key: "klear_brand_v1", version: "1" }`
 * or `{ kind: "inline", text: "..." }`). Tool and retry settings
 * mirror IWO2's workflow_steps so Loop 6's state machine port has a
 * stable shape.
 *
 * `assigned_sub_agent_key` is a free-form string in Phase 3.1 (no
 * FK to a sub_agents table yet — that table may land in a later
 * loop if we mirror IWO2's sub_agents).
 */
export const workflowTemplateSteps = pgTable(
  "workflow_template_steps",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    templateId: uuid("template_id")
      .notNull()
      .references(() => workflowTemplates.id, { onDelete: "cascade" }),
    stepKey: varchar("step_key", { length: 128 }).notNull(),
    stepOrder: integer("step_order").notNull(),
    displayName: varchar("display_name", { length: 256 }).notNull(),
    assignedSubAgentKey: varchar("assigned_sub_agent_key", {
      length: 64,
    }),
    promptRef: jsonb("prompt_ref"),
    retryPolicy: jsonb("retry_policy"),
    timeoutMs: integer("timeout_ms"),
    toolIds: jsonb("tool_ids"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqTemplateKey: unique("workflow_template_steps_template_key_uniq").on(
      t.templateId,
      t.stepKey
    ),
    uniqTemplateOrder: unique("workflow_template_steps_template_order_uniq").on(
      t.templateId,
      t.stepOrder
    ),
  })
);

export type WorkflowTemplateStep = typeof workflowTemplateSteps.$inferSelect;
export type NewWorkflowTemplateStep =
  typeof workflowTemplateSteps.$inferInsert;
