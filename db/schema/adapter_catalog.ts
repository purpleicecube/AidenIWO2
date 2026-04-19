import {
  pgTable,
  uuid,
  varchar,
  text,
  timestamp,
  pgEnum,
} from "drizzle-orm/pg-core";

export const adapterCategoryEnum = pgEnum("adapter_category", [
  "design_render",
  "storage",
  "campaign",
  "crm",
  "other",
]);

export const adapterCatalogStatusEnum = pgEnum("adapter_catalog_status", [
  "active",
  "beta",
  "deprecated",
]);

/**
 * Global catalog of adapter kinds the platform supports. Tenant-agnostic
 * — enabling / configuring per tenant lives in `client_adapter_configs`.
 *
 * Per IWO3_LOOP_3_APPROVAL_DECISIONS §ADR-012 guardrail: the catalog is
 * **not** Gamma-shaped. Loop 3 seeds seven categories (Gamma, Google
 * Drive, email campaign, Figma, Stitch, Claude Design, CRM) even though
 * only Gamma is exercised by a test-double adapter in Phase 3.4.
 */
export const adapterCatalog = pgTable("adapter_catalog", {
  id: uuid("id").primaryKey().defaultRandom(),
  adapterKey: varchar("adapter_key", { length: 64 }).notNull().unique(),
  displayName: varchar("display_name", { length: 128 }).notNull(),
  category: adapterCategoryEnum("category").notNull(),
  description: text("description"),
  contractVersion: varchar("contract_version", { length: 32 })
    .notNull()
    .default("v0"),
  status: adapterCatalogStatusEnum("status").notNull().default("active"),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type AdapterCatalogRow = typeof adapterCatalog.$inferSelect;
export type NewAdapterCatalogRow = typeof adapterCatalog.$inferInsert;
