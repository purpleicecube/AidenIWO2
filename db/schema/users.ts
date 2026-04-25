import {
  pgTable,
  uuid,
  varchar,
  timestamp,
  pgEnum,
} from "drizzle-orm/pg-core";

export const userStatusEnum = pgEnum("user_status", ["active", "disabled"]);

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: varchar("email", { length: 320 }).notNull().unique(),
  displayName: varchar("display_name", { length: 256 }).notNull(),
  status: userStatusEnum("status").notNull().default("active"),
  /**
   * Beta-1 ε.3 / Q2 — production auth password storage.
   * Format: pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>
   * NULL → user has no password yet (seed-only / pre-bootstrap state).
   */
  passwordHash: varchar("password_hash", { length: 512 }),
  passwordUpdatedAt: timestamp("password_updated_at", {
    withTimezone: true,
  }),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type User = typeof users.$inferSelect;
export type NewUser = typeof users.$inferInsert;
