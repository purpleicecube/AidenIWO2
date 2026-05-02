import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  boolean,
  integer,
  timestamp,
  unique,
  index,
} from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { llmConfigs } from "./llm_configs";
import { clients } from "./clients";
import { users } from "./users";

/**
 * Beta-2 phase 0.3.1 — versioned history for `llm_configs`.
 *
 * Every mutation to `llm_configs` (PATCH, bulk_apply, rollback, create)
 * snapshots a full row here BEFORE the live row is updated. Rollback =
 * pick a prior snapshot, write a new version with `change_action = 'rollback'`
 * carrying that snapshot's fields, then UPDATE `llm_configs` to match.
 *
 * Rationale (CODEX 2026-05-01):
 *   - Full-row snapshot is simpler than delta — rollback is one row read.
 *   - History rows are immutable; iwo3_app gets SELECT + INSERT only.
 *   - No "current_version_id" pointer on llm_configs; the live row IS
 *     the current state. Versions reconstruct prior state on demand.
 *   - `change_action` enum captures cause: initial / create / update /
 *     rollback. (`bulk_apply` records as `update` per entry.)
 */
export const llmConfigVersions = pgTable(
  "llm_config_versions",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    llmConfigId: uuid("llm_config_id")
      .notNull()
      .references(() => llmConfigs.id, { onDelete: "cascade" }),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "cascade" }),
    versionNumber: integer("version_number").notNull(),

    // Full snapshot of the live row at the time this version was written
    agentRole: varchar("agent_role", { length: 64 }).notNull(),
    provider: varchar("provider", { length: 32 }).notNull(),
    model: varchar("model", { length: 128 }).notNull(),
    baseUrl: varchar("base_url", { length: 256 }),
    credentialRef: varchar("credential_ref", { length: 256 }).notNull(),
    systemPrompt: text("system_prompt"),
    options: jsonb("options"),
    enabled: boolean("enabled").notNull(),
    notes: text("notes"),
    displayName: varchar("display_name", { length: 160 }).notNull(),
    description: text("description"),

    // Provenance
    changeAction: varchar("change_action", { length: 32 }).notNull(),
    changeReason: text("change_reason"),
    changedFields: text("changed_fields").array(),
    rolledBackFromVersionId: uuid("rolled_back_from_version_id"),

    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    createdByUserId: uuid("created_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
  },
  (t) => ({
    uniqPerConfig: unique("llm_config_versions_unique_per_config").on(
      t.llmConfigId,
      t.versionNumber
    ),
    lookupIdx: index("llm_config_versions_lookup_idx").on(
      t.llmConfigId,
      sql`${t.versionNumber} DESC`
    ),
    tenantIdx: index("llm_config_versions_tenant_idx").on(
      t.clientId,
      sql`${t.createdAt} DESC`
    ),
  })
);
