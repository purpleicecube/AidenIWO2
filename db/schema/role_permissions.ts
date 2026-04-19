/**
 * Loop 4 Phase 1 — role → permission default mapping.
 *
 * The Phase 4.2 `checkPermission` helper reads the user's active
 * membership row on (user_id, client_id) → role, then JOINs this table
 * to enumerate the role's grants. Per-user overrides live in
 * `permission_grants` (allow | deny, deny wins).
 *
 * Seeded defaults per IWO3_LOOP_4_APPROVAL_DECISIONS §Q2 (Darrel's
 * revised operator + agent_system grants):
 *   - owner         → all 69 permissions
 *   - admin         → all except `system:admin` and `user:revoke`
 *   - operator      → explicit list (see db/seeds/role_permissions.json)
 *                     including read-within-tenant, WO/WF/execution_cycle
 *                     write, output_package up to submit, apply_style
 *                     override. Excludes candidate select/reject, adapter
 *                     config/policy, audit_log:read, approve_send.
 *   - reviewer      → read-within-tenant + output_package:validate +
 *                     output_candidate:select/reject + apply_style.
 *   - viewer        → read-within-tenant only.
 *   - agent_system  → narrow automation identity, fully explicit (no
 *                     wildcards): WO create/update, workflow update,
 *                     workflow_execution/step_run create/update,
 *                     execution_cycle create/reopen, output_package up to
 *                     submit, output_handoff create/record/update (never
 *                     approve_send), external_execution_result:create.
 *                     Excludes approve_send, credentials, audit log,
 *                     user/membership/client mgmt, any delete, any publish.
 */

import {
  pgTable,
  uuid,
  timestamp,
  unique,
} from "drizzle-orm/pg-core";
import { membershipRoleEnum } from "./client_memberships";
import { permissions } from "./permissions";

export const rolePermissions = pgTable(
  "role_permissions",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    role: membershipRoleEnum("role").notNull(),
    permissionId: uuid("permission_id")
      .notNull()
      .references(() => permissions.id, { onDelete: "cascade" }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqRolePermission: unique("role_permissions_role_permission_uniq").on(
      t.role,
      t.permissionId
    ),
  })
);

export type RolePermission = typeof rolePermissions.$inferSelect;
export type NewRolePermission = typeof rolePermissions.$inferInsert;
