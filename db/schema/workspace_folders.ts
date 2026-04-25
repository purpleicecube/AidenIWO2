import {
  pgTable,
  uuid,
  varchar,
  timestamp,
  index,
  unique,
  type AnyPgColumn,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";

/**
 * Pre-Beta Loop δ.1 — Workspace folder tree.
 *
 * Per architect decision (IWO3_PRE_BETA_PRODUCT_SURFACE_REMEDIATION_
 * PRESTART_QUESTIONS_v0.1.0.md § Workspace storage substrate B), the
 * workspace tree lives in this dedicated table while files live in
 * the existing `artifacts` table joined via `artifacts.workspace_folder_id`.
 *
 * Per-tenant root: each client has exactly one root folder
 * (parent_folder_id IS NULL, name = '/'). All other folders descend.
 *
 * Soft-delete semantics: `deleted_at IS NOT NULL` hides the folder
 * (and its contents) from operator queries but keeps the row for
 * audit/forensics. Hard delete is operator-explicit (Beta scope).
 */
export const workspaceFolders = pgTable(
  "workspace_folders",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    /**
     * NULL = tenant root. Self-FK creates the tree.
     */
    parentFolderId: uuid("parent_folder_id").references(
      (): AnyPgColumn => workspaceFolders.id,
      { onDelete: "restrict" }
    ),
    name: varchar("name", { length: 256 }).notNull(),
    createdByUserId: uuid("created_by_user_id")
      .notNull()
      .references(() => users.id, { onDelete: "restrict" }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    /** NULL = active; non-NULL = soft-deleted */
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
  },
  (t) => ({
    idxClientParent: index("workspace_folders_client_parent_idx").on(
      t.clientId,
      t.parentFolderId
    ),
    /**
     * Sibling-name uniqueness — enforced at the row level so two
     * folders can't share a parent + name. Postgres treats NULLs as
     * distinct in UNIQUE indexes; the tenant-root case (parent IS NULL)
     * is handled application-side by ensuring exactly one root per
     * tenant via a sentinel name.
     */
    uniqSiblingName: unique("workspace_folders_sibling_name_uniq").on(
      t.clientId,
      t.parentFolderId,
      t.name
    ),
  })
);

export type WorkspaceFolder = typeof workspaceFolders.$inferSelect;
export type NewWorkspaceFolder = typeof workspaceFolders.$inferInsert;
