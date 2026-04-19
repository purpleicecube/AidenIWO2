import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  boolean,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { adapterCatalog } from "./adapter_catalog";

export const clientAdapterConfigStatusEnum = pgEnum(
  "client_adapter_config_status",
  ["active", "paused", "revoked"]
);

/**
 * Per-tenant enable/configure row for a catalog adapter. Carries the
 * `credential_ref` placeholder that the adapter uses at runtime; raw
 * secrets never live here. Tenant isolation required on every read.
 */
export const clientAdapterConfigs = pgTable(
  "client_adapter_configs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    adapterCatalogId: uuid("adapter_catalog_id")
      .notNull()
      .references(() => adapterCatalog.id, { onDelete: "restrict" }),
    enabled: boolean("enabled").notNull().default(true),
    credentialRef: varchar("credential_ref", { length: 256 }),
    config: jsonb("config"),
    status: clientAdapterConfigStatusEnum("status").notNull().default("active"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientAdapter: unique("client_adapter_configs_client_adapter_uniq").on(
      t.clientId,
      t.adapterCatalogId
    ),
  })
);

export type ClientAdapterConfig = typeof clientAdapterConfigs.$inferSelect;
export type NewClientAdapterConfig = typeof clientAdapterConfigs.$inferInsert;
