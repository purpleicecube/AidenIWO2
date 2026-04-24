import {
  pgTable,
  uuid,
  varchar,
  text,
  boolean,
  integer,
  timestamp,
  unique,
} from "drizzle-orm/pg-core";
import { adapterCatalog } from "./adapter_catalog";

/**
 * Actions each adapter can perform. Tenant-agnostic — which tenant is
 * allowed to invoke which action is controlled by `adapter_action_policies`.
 *
 * `action_key` examples:
 *   - gamma: generate | render_from_template | export_pptx | export_pdf
 *   - google_drive: upload | publish_share
 *   - email_campaign: compose | test_send | send
 *   - figma / stitch / claude_design: generate | publish
 *   - crm: create_record | update_record | delete_record
 *
 * Loop 9 Phase 9.1 addition: `poll_timeout_seconds` — how long the
 * dispatcher will wait before watchdog-expiring a still-processing
 * dispatch for this action. `NULL` means "use the runtime default"
 * (Phase 9.3 wires the default + consumption path). Healthy long
 * renders within the window must NOT trigger watchdog.
 */
export const adapterActions = pgTable(
  "adapter_actions",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    adapterCatalogId: uuid("adapter_catalog_id")
      .notNull()
      .references(() => adapterCatalog.id, { onDelete: "cascade" }),
    actionKey: varchar("action_key", { length: 64 }).notNull(),
    displayName: varchar("display_name", { length: 128 }).notNull(),
    description: text("description"),
    requiresOutputPackage: boolean("requires_output_package")
      .notNull()
      .default(true),
    pollTimeoutSeconds: integer("poll_timeout_seconds"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqCatalogAction: unique("adapter_actions_catalog_action_uniq").on(
      t.adapterCatalogId,
      t.actionKey
    ),
  })
);

export type AdapterAction = typeof adapterActions.$inferSelect;
export type NewAdapterAction = typeof adapterActions.$inferInsert;
