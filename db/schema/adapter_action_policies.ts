import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { adapterCatalog } from "./adapter_catalog";

export const adapterPolicyModeEnum = pgEnum("adapter_policy_mode", [
  "none",
  "approval_required",
  "disallowed",
]);

/**
 * Per-tenant policy for an (adapter, action) pair. The service-layer
 * resolver reads this table before every adapter invocation:
 *
 *   - row missing → default `none` (no approval, no block)
 *   - row = `none` → explicitly-approved (documentation)
 *   - row = `approval_required` → must attach an approval ref before submit
 *   - row = `disallowed` → hard reject
 *
 * Tenant-scoped by `client_id`. Action key is a soft reference into
 * `adapter_actions.action_key` (no FK; the action may exist on the
 * catalog before a tenant-specific policy is written, and we want the
 * policy table to be authoritative on intent regardless of action-catalog
 * state).
 */
export const adapterActionPolicies = pgTable(
  "adapter_action_policies",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    adapterCatalogId: uuid("adapter_catalog_id")
      .notNull()
      .references(() => adapterCatalog.id, { onDelete: "restrict" }),
    actionKey: varchar("action_key", { length: 64 }).notNull(),
    mode: adapterPolicyModeEnum("mode").notNull(),
    reason: text("reason"),
    metadata: jsonb("metadata"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientAdapterAction: unique(
      "adapter_action_policies_cfg_action_uniq"
    ).on(t.clientId, t.adapterCatalogId, t.actionKey),
  })
);

export type AdapterActionPolicy = typeof adapterActionPolicies.$inferSelect;
export type NewAdapterActionPolicy =
  typeof adapterActionPolicies.$inferInsert;
