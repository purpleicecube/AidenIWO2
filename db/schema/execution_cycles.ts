import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  integer,
  timestamp,
  pgEnum,
  unique,
  index,
  type AnyPgColumn,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";
import { workOrders } from "./work_orders";

export const executionCycleTriggerEnum = pgEnum("execution_cycle_trigger", [
  "new",
  "retry",
  "reopen",
  "unblock",
  "watchdog",
  "admin_repair",
  "candidate_request_more",
]);

/**
 * Execution cycle — a single processing attempt against a WO, per
 * ADR-003 §retry/reopen semantics. `cycle_number` is monotonic per
 * work order (1 = first attempt). `prior_cycle_id` self-references
 * the previous cycle for lineage.
 *
 * Loop 3 Phase 1 persists cycles; Loop 6 wires the state machine
 * that creates and terminates them. `terminal_status` captures the
 * WO status at the moment the cycle ended (e.g. `completed`,
 * `failed`, `blocked`); it is free-form varchar in Phase 3.1 to
 * avoid coupling to the WO enum during Loop 6's expansion.
 */
export const executionCycles = pgTable(
  "execution_cycles",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    workOrderId: uuid("work_order_id")
      .notNull()
      .references(() => workOrders.id, { onDelete: "cascade" }),
    cycleNumber: integer("cycle_number").notNull(),
    trigger: executionCycleTriggerEnum("trigger").notNull(),
    initiatedByUserId: uuid("initiated_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    reason: text("reason"),
    priorCycleId: uuid("prior_cycle_id").references(
      (): AnyPgColumn => executionCycles.id,
      { onDelete: "set null" }
    ),
    startedAt: timestamp("started_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    terminalStatus: varchar("terminal_status", { length: 64 }),
    metadata: jsonb("metadata"),
  },
  (t) => ({
    uniqWoCycle: unique("execution_cycles_wo_cycle_uniq").on(
      t.workOrderId,
      t.cycleNumber
    ),
    idxClientStarted: index("execution_cycles_client_started_idx").on(
      t.clientId,
      t.startedAt
    ),
  })
);

export type ExecutionCycle = typeof executionCycles.$inferSelect;
export type NewExecutionCycle = typeof executionCycles.$inferInsert;
