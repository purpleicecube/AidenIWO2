/**
 * Loop Eta — global tool catalog (tenant-agnostic registry).
 * MegaLoop Theta — extended for full IWO2 Tools Locker parity.
 *
 * Architectural lock from IWO3_LOOP_ETA_SCOPE_PROPOSAL §3 +
 * IWO3_MEGALOOP_THETA_TOOLS_LOCKER_SCOPE §D1:
 *   - Executable tool truth lives in code (apps/api-fastapi/runtime/aiden_tools.py).
 *   - This table provides metadata for UI, assignment, grouping, status,
 *     governance, and operator-driven editing. DB rows alone do not
 *     make a tool runnable — `runtime_status` documents whether a
 *     runnable handler exists in the code registry, is delegated through
 *     MCP, is a prompt-injection skill template only, or is
 *     planned-but-not-shipped.
 *   - The Theta column set adds skill content, source code, MCP config,
 *     credentials editor refs, I/O contracts, governance (lease /
 *     concurrency / restricted), and operator-facing usage instructions
 *     so the IWO2 Tools Locker UI works on top of this row shape.
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
  integer,
  timestamp,
  pgEnum,
  index,
} from "drizzle-orm/pg-core";
import { users } from "./users";

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

// MegaLoop Theta revisions (D9.2, 2026-05-03) — pure execution-truth
// vocabulary. Old `mcp` value retired (transport mode, not exec
// truth — captured by tool_type enum instead). Old `skill_only`
// generalised to `catalog_only` (skill is just one shape of
// catalog-only metadata). Two new values:
//   catalog_only — metadata-only row, no runnable handler in
//                  aiden_tools.TOOL_REGISTRY
//   legacy       — retired tool kept for audit/history forensics
export const toolRuntimeStatusEnum = pgEnum("tool_runtime_status", [
  "runnable",
  "catalog_only",
  "planned",
  "legacy",
]);

export const toolDefaultTierEnum = pgEnum("tool_default_tier", [
  "tier_1",
  "tier_2",
  "either",
]);

// MegaLoop Theta — IWO2-parity 7-value tool type. Distinct from
// `runtime_status` (which is the truth gate against
// `aiden_tools.TOOL_REGISTRY`). This column answers the operator-facing
// question "what kind of integration is this?" and drives the Identity
// tab radio in the Tools Locker.
export const toolTypeEnum = pgEnum("tool_type", [
  "skill",
  "python_code",
  "slash_command",
  "cli",
  "api",
  "webhook",
  "mcp_server",
]);

// MegaLoop Theta — governance access tier. Mirrors IWO2's `accessTier`
// enum used to gate which tier of agents may check out a tool. Loop θ.1
// persists the value; runtime enforcement is deferred per scope
// §Out-of-scope.
export const toolAccessTierEnum = pgEnum("tool_access_tier", [
  "any",
  "tier_1",
  "tier_2",
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

    // ── MegaLoop Theta extensions ────────────────────────────────
    // D1.1 revision (2026-05-03): tool_type is NOT NULL after the
    // 0024 migration — the Pydantic create body required it from day
    // one and the UI conditional-tab logic depends on a value being
    // present. Previously nullable to keep the 0023 migration
    // single-pass; that's no longer needed.
    toolType: toolTypeEnum("tool_type").notNull(),
    versionLabel: varchar("version_label", { length: 32 })
      .notNull()
      .default("1.0.0"),
    executionMode: varchar("execution_mode", { length: 64 })
      .notNull()
      .default("prompt_injection"),
    // Skill tab
    skillContent: text("skill_content"),
    skillInstructions: text("skill_instructions"),
    triggerConditions: jsonb("trigger_conditions").notNull().default([]),
    // Code tab
    sourceCode: text("source_code"),
    entryPoint: varchar("entry_point", { length: 256 }),
    runtimeEnvironment: varchar("runtime_environment", { length: 64 }),
    sandboxConfig: jsonb("sandbox_config").notNull().default({}),
    // MCP tab
    mcpConfig: jsonb("mcp_config").notNull().default({}),
    // Creds tab
    credentials: jsonb("credentials").notNull().default([]),
    // Access tab
    usageInstructions: text("usage_instructions"),
    // I/O tab
    inputSchema: jsonb("input_schema").notNull().default({}),
    outputSchema: jsonb("output_schema").notNull().default({}),
    // Govern tab
    accessTier: toolAccessTierEnum("access_tier").notNull().default("any"),
    maxConcurrent: integer("max_concurrent").notNull().default(0),
    defaultLeaseSeconds: integer("default_lease_seconds")
      .notNull()
      .default(300),
    maxLeaseSeconds: integer("max_lease_seconds").notNull().default(3600),
    dailyUsageLimit: integer("daily_usage_limit"),
    costCeilingPerDay: text("cost_ceiling_per_day"),
    requiresApproval: boolean("requires_approval").notNull().default(false),
    restricted: boolean("restricted").notNull().default(false),
    restrictedReason: text("restricted_reason"),
    restrictedByUserId: uuid("restricted_by_user_id").references(
      () => users.id,
      { onDelete: "set null" }
    ),

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
