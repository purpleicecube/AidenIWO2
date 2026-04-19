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

export const repositoryConnectorTypeEnum = pgEnum(
  "repository_connector_type",
  ["google_drive", "dropbox", "github", "s3", "local", "custom"]
);

export const repositoryBindingStatusEnum = pgEnum(
  "repository_binding_status",
  ["active", "paused", "revoked"]
);

export const repositoryBindings = pgTable(
  "repository_bindings",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    bindingKey: varchar("binding_key", { length: 128 }).notNull(),
    connectorType: repositoryConnectorTypeEnum("connector_type").notNull(),
    scope: jsonb("scope"),
    credentialRef: varchar("credential_ref", { length: 256 }),
    allowedLocations: jsonb("allowed_locations"),
    freshnessPolicy: jsonb("freshness_policy"),
    status: repositoryBindingStatusEnum("status").notNull().default("active"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientKey: unique("repository_bindings_client_key_uniq").on(
      t.clientId,
      t.bindingKey
    ),
  })
);

export type RepositoryBinding = typeof repositoryBindings.$inferSelect;
export type NewRepositoryBinding = typeof repositoryBindings.$inferInsert;
