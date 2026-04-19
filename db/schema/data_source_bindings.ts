import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";

export const dataSourceConnectorTypeEnum = pgEnum(
  "data_source_connector_type",
  ["postgres", "bigquery", "snowflake", "sheets", "rest_api", "custom"]
);

export const dataSourceBindingStatusEnum = pgEnum(
  "data_source_binding_status",
  ["active", "paused", "revoked"]
);

export const dataSourceBindings = pgTable(
  "data_source_bindings",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    bindingKey: varchar("binding_key", { length: 128 }).notNull(),
    connectorType: dataSourceConnectorTypeEnum("connector_type").notNull(),
    scope: jsonb("scope"),
    credentialRef: varchar("credential_ref", { length: 256 }),
    allowedLocations: jsonb("allowed_locations"),
    freshnessPolicy: jsonb("freshness_policy"),
    status: dataSourceBindingStatusEnum("status").notNull().default("active"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientKey: unique("data_source_bindings_client_key_uniq").on(
      t.clientId,
      t.bindingKey
    ),
  })
);

export type DataSourceBinding = typeof dataSourceBindings.$inferSelect;
export type NewDataSourceBinding = typeof dataSourceBindings.$inferInsert;
