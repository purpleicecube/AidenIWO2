import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  timestamp,
  pgEnum,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { adapterCatalog } from "./adapter_catalog";

export const adapterCredentialStatusEnum = pgEnum(
  "adapter_credential_status",
  ["active", "rotation_due", "revoked", "expired"]
);

/**
 * Per-tenant, per-adapter credential reference. NEVER stores raw secret
 * material. `credential_ref` points at a secret-manager entry (or a
 * `credential_ref:dev-local-*` placeholder in dev). Rotation cadence
 * is tracked by `rotation_due_at`; Loop 6+ adds the rotation scheduler.
 */
export const adapterCredentials = pgTable("adapter_credentials", {
  id: uuid("id").primaryKey().defaultRandom(),
  clientId: uuid("client_id")
    .notNull()
    .references(() => clients.id, { onDelete: "restrict" }),
  adapterCatalogId: uuid("adapter_catalog_id")
    .notNull()
    .references(() => adapterCatalog.id, { onDelete: "restrict" }),
  credentialRef: varchar("credential_ref", { length: 256 }).notNull(),
  scope: jsonb("scope"),
  rotationDueAt: timestamp("rotation_due_at", { withTimezone: true }),
  status: adapterCredentialStatusEnum("status").notNull().default("active"),
  metadata: jsonb("metadata"),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type AdapterCredential = typeof adapterCredentials.$inferSelect;
export type NewAdapterCredential = typeof adapterCredentials.$inferInsert;
