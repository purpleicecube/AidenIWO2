import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  integer,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { workflowExecutions } from "./workflow_executions";

export const workflowStepRunStatusEnum = pgEnum("workflow_step_run_status", [
  "pending",
  "running",
  "completed",
  "failed",
  "skipped",
]);

/**
 * Per-step run inside a workflow execution. Loop 3 Phase 1 persists
 * the shape only; actual step-dispatch behavior (PM review, revision,
 * escalation, PocketFlow integration) ships with Loop 6's state
 * machine.
 */
export const workflowStepRuns = pgTable(
  "workflow_step_runs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    executionId: uuid("execution_id")
      .notNull()
      .references(() => workflowExecutions.id, { onDelete: "cascade" }),
    stepKey: varchar("step_key", { length: 128 }).notNull(),
    stepOrder: integer("step_order").notNull(),
    status: workflowStepRunStatusEnum("status").notNull().default("pending"),
    input: jsonb("input"),
    output: jsonb("output"),
    pmReview: jsonb("pm_review"),
    revisionAttempt: integer("revision_attempt").notNull().default(0),
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
    uniqExecStep: unique("workflow_step_runs_execution_step_uniq").on(
      t.executionId,
      t.stepKey
    ),
  })
);

export type WorkflowStepRun = typeof workflowStepRuns.$inferSelect;
export type NewWorkflowStepRun = typeof workflowStepRuns.$inferInsert;
