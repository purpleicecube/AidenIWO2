/**
 * Loop 4 Phase 1 — flat permission vocabulary table.
 *
 * Keyed by `permission_key` (colon-separated `resource:verb`, e.g.
 * `work_order:create`). Fully locked up-front per
 * IWO3_LOOP_4_APPROVAL_DECISIONS §Q1 (`lock_upfront`) so the Phase 4.2
 * authz helper can fail closed on any reference to an unknown key.
 *
 * Scope enum (consumed by Phase 4.2 checker):
 *   - `global`   — cross-tenant (super admin / platform concerns)
 *   - `tenant`   — scoped to (user, client) via role_permissions + the
 *                  Loop 2 client_memberships row
 *   - `resource` — per-record grants; reserved for Loop 5+, not used in v0
 *
 * No seeds ship runtime grants in `permission_grants`; seeds populate
 * `permissions` + `role_permissions` only. Per-user overrides are a
 * runtime concern (admin action, Phase 4.2+ API).
 */

import {
  pgTable,
  uuid,
  varchar,
  text,
  timestamp,
  pgEnum,
} from "drizzle-orm/pg-core";

export const permissionScopeEnum = pgEnum("permission_scope", [
  "global",
  "tenant",
  "resource",
]);

export const permissions = pgTable("permissions", {
  id: uuid("id").primaryKey().defaultRandom(),
  permissionKey: varchar("permission_key", { length: 96 }).notNull().unique(),
  displayName: varchar("display_name", { length: 160 }).notNull(),
  description: text("description"),
  scope: permissionScopeEnum("scope").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type Permission = typeof permissions.$inferSelect;
export type NewPermission = typeof permissions.$inferInsert;
