import {
  pgTable,
  uuid,
  varchar,
  text,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";

export const workflowStatusEnum = pgEnum("workflow_status", [
  "active",
  "paused",
  "archived",
]);

/**
 * Workflow — repeatable / reusable pipeline (per ADR-003 §WO-vs-WF).
 *
 * Tenant-scoped logical container. Concrete versions live in
 * `workflow_templates` so published vs draft vs deprecated lifecycle
 * stays on the version, not the workflow.
 */
export const workflows = pgTable(
  "workflows",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    key: varchar("key", { length: 128 }).notNull(),
    displayName: varchar("display_name", { length: 256 }).notNull(),
    description: text("description"),
    status: workflowStatusEnum("status").notNull().default("active"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientKey: unique("workflows_client_key_uniq").on(t.clientId, t.key),
  })
);

export type Workflow = typeof workflows.$inferSelect;
export type NewWorkflow = typeof workflows.$inferInsert;
