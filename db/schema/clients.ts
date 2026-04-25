import {
  pgTable,
  uuid,
  varchar,
  timestamp,
  pgEnum,
  integer,
} from "drizzle-orm/pg-core";

export const deploymentModeEnum = pgEnum("deployment_mode", [
  "dedicated_single_client",
  "shared_multi_tenant",
  "hybrid",
]);

export const clientStatusEnum = pgEnum("client_status", [
  "active",
  "suspended",
]);

export const clients = pgTable("clients", {
  id: uuid("id").primaryKey().defaultRandom(),
  designation: varchar("designation", { length: 128 }).notNull().unique(),
  displayName: varchar("display_name", { length: 256 }).notNull(),
  deploymentMode: deploymentModeEnum("deployment_mode").notNull(),
  status: clientStatusEnum("status").notNull().default("active"),
  /**
   * Beta-1 ε.1 / Q1 — per-tenant LLM per-WO token ceiling override.
   * NULL = use platform default (DEFAULT_PER_WO_CEILING = 50_000).
   * Architect lock: simplest schema; per-role overrides remain GA scope.
   */
  llmPerWoCeiling: integer("llm_per_wo_ceiling"),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type Client = typeof clients.$inferSelect;
export type NewClient = typeof clients.$inferInsert;
