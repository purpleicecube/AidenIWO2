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

export const workOrderStatusEnum = pgEnum("work_order_status", [
  "pending",
  "processing",
  "blocked",
  "awaiting_operator",
  "completed",
  "done",
  "failed",
  "deferred",
  "cancelled",
]);

export const workOrderPriorityEnum = pgEnum("work_order_priority", [
  "low",
  "medium",
  "high",
  "critical",
]);

/**
 * Work Order — one-time execution (per ADR-003 §WO-vs-WF).
 *
 * Loop 3 Phase 1 persists the shape only. State-machine transitions
 * (retry / reopen / unblock / watchdog / terminal governance) land in
 * Loop 6 per IWO3_LOOP_3_APPROVAL_DECISIONS §Q2.
 */
export const workOrders = pgTable(
  "work_orders",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    title: varchar("title", { length: 512 }).notNull(),
    description: text("description"),
    type: varchar("type", { length: 64 }).notNull().default("standard"),
    priority: workOrderPriorityEnum("priority").notNull().default("medium"),
    status: workOrderStatusEnum("status").notNull().default("pending"),
    submittedByUserId: uuid("submitted_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    correlationId: varchar("correlation_id", { length: 128 }),
    gccMemory: jsonb("gcc_memory"),
    requestedOutputs: jsonb("requested_outputs"),
    deferredUntil: timestamp("deferred_until", { withTimezone: true }),
    deferredReason: text("deferred_reason"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    idxClientStatusCreated: index("work_orders_client_status_created_idx").on(
      t.clientId,
      t.status,
      t.createdAt
    ),
  })
);

export type WorkOrder = typeof workOrders.$inferSelect;
export type NewWorkOrder = typeof workOrders.$inferInsert;
