/**
 * Loop Eta — global tool catalog (tenant-agnostic registry).
 *
 * Architectural lock from IWO3_LOOP_ETA_SCOPE_PROPOSAL §3:
 *   - Executable tool truth lives in code (apps/api-fastapi/runtime/aiden_tools.py).
 *   - This table provides metadata for UI, assignment, grouping, status,
 *     and future expansion. DB rows alone do not make a tool runnable —
 *     `runtime_status` documents whether a runnable handler exists in the
 *     code registry, is delegated through MCP, is a prompt-injection skill
 *     template only, or is planned-but-not-shipped.
 *
 * The table is global (tenant-agnostic) — assignments per (tenant, agent)
 * live in `sub_agent_tools`. Adding a new tool means seeding one row here
 * + (when runnable) registering its handler in `aiden_tools.TOOL_REGISTRY`.
 *
 * Provenance:
 *   - `iwo2_origin` carries the IWO2 tool key (e.g. 'brave-search') when
 *     the tool ports parity from IWO2; NULL for IWO3-native tools and
 *     net-new tools authored in this loop.
 */

import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  boolean,
  timestamp,
  pgEnum,
  index,
} from "drizzle-orm/pg-core";

export const toolCategoryEnum = pgEnum("tool_category", [
  "search",
  "document",
  "rendering",
  "design",
  "data",
  "ops",
  "introspection",
  "skill_only",
]);

export const toolRuntimeStatusEnum = pgEnum("tool_runtime_status", [
  "runnable",
  "skill_only",
  "mcp",
  "planned",
]);

export const toolDefaultTierEnum = pgEnum("tool_default_tier", [
  "tier_1",
  "tier_2",
  "either",
]);

export const toolCatalog = pgTable(
  "tool_catalog",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    toolKey: varchar("tool_key", { length: 96 }).notNull().unique(),
    displayName: varchar("display_name", { length: 160 }).notNull(),
    description: text("description").notNull(),
    category: toolCategoryEnum("category").notNull(),
    runtimeStatus: toolRuntimeStatusEnum("runtime_status").notNull(),
    /** JSON schema for handler args; informational, not server-validated. */
    argsSchema: jsonb("args_schema").notNull().default({}),
    /** Python qualified name in aiden_tools.py registry, or 'mcp:server:tool'. */
    handlerRef: varchar("handler_ref", { length: 256 }),
    defaultTier: toolDefaultTierEnum("default_tier").notNull(),
    /** IWO2 tool key when ported from parity; NULL for IWO3-native or net-new. */
    iwo2Origin: varchar("iwo2_origin", { length: 96 }),
    enabled: boolean("enabled").notNull().default(true),
    notes: text("notes"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    catalogCategoryStatusIdx: index("tool_catalog_category_status_idx").on(
      t.category,
      t.runtimeStatus
    ),
    catalogTierIdx: index("tool_catalog_default_tier_idx").on(t.defaultTier),
  })
);

export type ToolCatalogRow = typeof toolCatalog.$inferSelect;
export type NewToolCatalogRow = typeof toolCatalog.$inferInsert;
