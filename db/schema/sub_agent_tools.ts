/**
 * Loop Eta — per-(tenant, llm_config) tool assignments.
 *
 * One row per (llm_config_id, tool_key) — the rows that grant a Tier 1 / 1.5 /
 * 2 sub-agent permission to actually invoke a runtime-resolvable tool from
 * `tool_catalog`. The Tier 2 invocation pipeline reads this table as part
 * of pre-execution authz; missing rows trip the
 * `sub_agent.tool_unauthorized` audit path and the LLM is re-invoked with
 * a `[TOOL DENIED]` prompt fragment.
 *
 * Architectural lock from IWO3_LOOP_ETA_SCOPE_PROPOSAL §3:
 *   - Tenant-scoped via `client_id`; FORCE ROW LEVEL SECURITY in the
 *     0022 migration mirrors the Loop 4 Phase 4.3 pattern.
 *   - `tool_key` is FK to `tool_catalog.tool_key` (UNIQUE column) so the
 *     vocabulary stays locked to the catalog.
 *   - `enabled=false` is the soft-revoke path; the row stays for history.
 *     There is NO DELETE endpoint — the PUT `/llm/configs/{id}/tools/{key}`
 *     toggle drives enabled on/off.
 */

import {
  pgTable,
  uuid,
  varchar,
  text,
  boolean,
  timestamp,
  unique,
  index,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { llmConfigs } from "./llm_configs";
import { users } from "./users";
import { toolCatalog } from "./tool_catalog";

export const subAgentTools = pgTable(
  "sub_agent_tools",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "cascade" }),
    llmConfigId: uuid("llm_config_id")
      .notNull()
      .references(() => llmConfigs.id, { onDelete: "cascade" }),
    /** FK to tool_catalog.tool_key (UNIQUE). Enforced at the SQL layer. */
    toolKey: varchar("tool_key", { length: 96 })
      .notNull()
      .references(() => toolCatalog.toolKey, { onDelete: "restrict" }),
    enabled: boolean("enabled").notNull().default(true),
    grantedAt: timestamp("granted_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    grantedByUserId: uuid("granted_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    notes: text("notes"),
  },
  (t) => ({
    uniqAssignment: unique("sub_agent_tools_unique_per_config_tool").on(
      t.llmConfigId,
      t.toolKey
    ),
    tenantConfigIdx: index("sub_agent_tools_tenant_config_idx").on(
      t.clientId,
      t.llmConfigId
    ),
    toolKeyIdx: index("sub_agent_tools_tool_key_idx").on(t.toolKey),
  })
);

export type SubAgentToolRow = typeof subAgentTools.$inferSelect;
export type NewSubAgentToolRow = typeof subAgentTools.$inferInsert;
