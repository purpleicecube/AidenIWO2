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
import { workflowTemplates } from "./workflow_templates";
import { workOrders } from "./work_orders";

export const workflowExecutionStatusEnum = pgEnum("workflow_execution_status", [
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
]);

/**
 * Workflow execution — a running instance of a template version.
 * `work_order_id` is nullable because a WF can run standalone (no
 * parent WO); when present, it ties the run to the WO that triggered
 * it. `client_id` is duplicated from the WO or from the template's
 * workflow for fast tenant-scoped queries (the canonical tenant is
 * always the template's workflow's client — enforced by isolation
 * tests).
 */
export const workflowExecutions = pgTable(
  "workflow_executions",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    templateId: uuid("template_id")
      .notNull()
      .references(() => workflowTemplates.id, { onDelete: "restrict" }),
    workOrderId: uuid("work_order_id").references(() => workOrders.id, {
      onDelete: "set null",
    }),
    status: workflowExecutionStatusEnum("status").notNull().default("pending"),
    currentStepKey: varchar("current_step_key", { length: 128 }),
    goal: text("goal"),
    finalWorkProduct: jsonb("final_work_product"),
    executiveReview: jsonb("executive_review"),
    startedAt: timestamp("started_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    idxClientStatusCreated: index(
      "workflow_executions_client_status_created_idx"
    ).on(t.clientId, t.status, t.createdAt),
  })
);

export type WorkflowExecution = typeof workflowExecutions.$inferSelect;
export type NewWorkflowExecution = typeof workflowExecutions.$inferInsert;
