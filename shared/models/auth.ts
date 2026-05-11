import { sql } from "drizzle-orm";
import { index, jsonb, pgTable, text, timestamp, uuid, varchar } from "drizzle-orm/pg-core";

export const sessions = pgTable(
  "sessions",
  {
    sid: varchar("sid").primaryKey(),
    sess: jsonb("sess").notNull(),
    expire: timestamp("expire").notNull(),
  },
  (table) => [index("IDX_session_expire").on(table.expire)]
);

/**
 * Users — IWO3-shape adaptation (Node Storage Adaptation Darkmode 2026-05-11).
 *
 * IWO2 stored a flat user with first/last name + profile_image_url +
 * top-level `role`. IWO3 (Loop 1 foundation) re-shaped users to:
 *
 *   - `display_name` instead of first_name/last_name
 *   - `status` text instead of soft-flags
 *   - no top-level `role` — role lives per-tenant in `client_memberships`
 *
 * This Drizzle model is the IWO3 shape so `db.select().from(users)`
 * doesn't reference columns that don't exist. The Node auth path was
 * fixed in lockstep (`server/replit_integrations/auth/storage.ts`,
 * `server/replit_integrations/auth/replitAuth.ts`,
 * `server/routes.ts:requireRole`) to read role from `client_memberships`.
 */
export const users = pgTable("users", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  email: varchar("email").unique(),
  displayName: text("display_name"),
  status: text("status").default("active"),
  passwordHash: varchar("password_hash"),
  passwordUpdatedAt: timestamp("password_updated_at", { withTimezone: true }),
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow(),
});

export type UpsertUser = typeof users.$inferInsert;
export type User = typeof users.$inferSelect;

/**
 * Client memberships — per-tenant role binding. IWO3-native (Loop 1).
 * Node needs read access here so `requireRole` can derive the operator's
 * effective role without relying on the non-existent `users.role` column.
 *
 * Path A-prime sandbox carve-out (ADR-035) does not require the sandbox
 * itself to be tenant-scoped — but operator role *resolution* still
 * needs to consult memberships to gate sandbox access.
 */
export const clientMemberships = pgTable("client_memberships", {
  id: uuid("id").primaryKey().defaultRandom(),
  clientId: uuid("client_id").notNull(),
  userId: varchar("user_id").notNull(),
  role: text("role").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow(),
});

export type ClientMembership = typeof clientMemberships.$inferSelect;
