import {
  pgTable,
  uuid,
  varchar,
  timestamp,
  pgEnum,
  integer,
  boolean,
  text,
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
  /**
   * Loop Iota — Memory V1 retrofit.
   *
   * memoryEnabled: per-tenant kill switch for the memory builder.
   *   true = assemble memory bundle (chat history + canonical facts +
   *   workspace retrieval + scratch) before each Tier-1 LLM call.
   *   false = bypass; emit `memory.bypassed` audit + run Tier-1 with no
   *   memory injection. Combined with the IWO3_MEMORY_INJECTION_ENABLED
   *   env-level kill switch.
   *
   * canonicalFactsBlob: denormalized concatenation of all .md files in
   *   the tenant's `Canonical Facts/` workspace folder. Hard-prepended
   *   to every Tier-1 chat turn at memory-budget priority 1 (never
   *   truncated). Authoritative. NULL = no canonical facts yet.
   *
   * canonicalFactsRevision: monotonic counter bumped by the workspace
   *   write hook whenever a file under `Canonical Facts/` changes.
   *   Cache key for the in-process LRU is (client_id, revision); bump
   *   invalidates the entry cleanly.
   */
  memoryEnabled: boolean("memory_enabled").notNull().default(true),
  canonicalFactsBlob: text("canonical_facts_blob"),
  canonicalFactsRevision: integer("canonical_facts_revision")
    .notNull()
    .default(0),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type Client = typeof clients.$inferSelect;
export type NewClient = typeof clients.$inferInsert;
