import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  timestamp,
  pgEnum,
} from "drizzle-orm/pg-core";
import { outputHandoffs } from "./output_handoffs";

export const externalExecutionResultStatusEnum = pgEnum(
  "external_execution_result_status",
  ["success", "partial", "failed", "unknown"]
);

/**
 * Persists the result an external system returned for a submitted
 * handoff. Many-to-one on `output_handoffs` — one handoff can receive
 * multiple callback / poll results (e.g. Gamma's async generation
 * emits a started event then a completed event).
 *
 * Tenant scope is transitive through `output_handoffs.client_id`;
 * service-layer reads MUST JOIN through the handoff.
 */
export const externalExecutionResults = pgTable(
  "external_execution_results",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    outputHandoffId: uuid("output_handoff_id")
      .notNull()
      .references(() => outputHandoffs.id, { onDelete: "cascade" }),
    status: externalExecutionResultStatusEnum("status").notNull(),
    receivedAt: timestamp("received_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    payloadRef: varchar("payload_ref", { length: 1024 }),
    errorMessage: text("error_message"),
    metadata: jsonb("metadata"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  }
);

export type ExternalExecutionResult =
  typeof externalExecutionResults.$inferSelect;
export type NewExternalExecutionResult =
  typeof externalExecutionResults.$inferInsert;
