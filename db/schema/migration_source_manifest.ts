import {
  pgTable,
  varchar,
  timestamp,
  pgEnum,
  text,
} from "drizzle-orm/pg-core";

export const manifestSourceEnum = pgEnum("manifest_source", [
  "iwo2_parity",
  "iwo3_native",
]);

export const manifestOwnerEnum = pgEnum("manifest_owner", [
  "drizzle",
  "alembic",
]);

export const migrationSourceManifest = pgTable("migration_source_manifest", {
  tableName: varchar("table_name", { length: 128 }).primaryKey(),
  source: manifestSourceEnum("source").notNull(),
  sourceVersion: varchar("source_version", { length: 64 }).notNull(),
  ownedBy: manifestOwnerEnum("owned_by").notNull(),
  introducedAt: timestamp("introduced_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  notes: text("notes"),
});

export type MigrationSourceManifestRow =
  typeof migrationSourceManifest.$inferSelect;
export type NewMigrationSourceManifestRow =
  typeof migrationSourceManifest.$inferInsert;
