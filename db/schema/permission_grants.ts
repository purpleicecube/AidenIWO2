/**
 * Loop 4 Phase 1 — per-user, per-tenant permission override.
 *
 * Applies *on top of* the `role_permissions` default. Row semantics:
 *   - `grant_type` = `allow` — user has this permission even if the role
 *                              mapping does not grant it
 *   - `grant_type` = `deny`  — user is explicitly denied this permission
 *                              even if their role would grant it
 *
 * Resolver precedence (Phase 4.2):
 *   explicit deny override > explicit allow override > role default > implicit deny
 *
 * Unique on (user_id, client_id, permission_id). The same user can hold
 * opposite overrides on different tenants (Klear allow / FFAI deny) but
 * cannot hold both allow and deny on the same (user, client, permission)
 * triple — that would be ambiguous.
 *
 * Empty in Loop 4 seeds — no runtime grants ship with the baseline; this
 * table is populated by Phase 4.2+ admin-action APIs.
 */

import {
  pgTable,
  uuid,
  text,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { users } from "./users";
import { clients } from "./clients";
import { permissions } from "./permissions";

export const permissionGrantTypeEnum = pgEnum("permission_grant_type", [
  "allow",
  "deny",
]);

export const permissionGrants = pgTable(
  "permission_grants",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "cascade" }),
    permissionId: uuid("permission_id")
      .notNull()
      .references(() => permissions.id, { onDelete: "cascade" }),
    grantType: permissionGrantTypeEnum("grant_type").notNull(),
    grantedByUserId: uuid("granted_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    reason: text("reason"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqUserClientPermission: unique(
      "permission_grants_user_client_permission_uniq"
    ).on(t.userId, t.clientId, t.permissionId),
  })
);

export type PermissionGrant = typeof permissionGrants.$inferSelect;
export type NewPermissionGrant = typeof permissionGrants.$inferInsert;
