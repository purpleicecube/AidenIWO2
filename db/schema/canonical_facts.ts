/**
 * Loop Kappa — Memory V1.5 canonical facts CRUD table.
 *
 * Authoritative authoring source for tenant canonical facts. Backed
 * by RLS-FORCE tenant isolation. The `clients.canonical_facts_blob`
 * column from Loop Iota (migration 0025) becomes a denormalized read
 * cache rebuilt by `refresh_canonical_facts_from_table()` whenever
 * this table has rows for the tenant. The folder-driven path
 * (`Canonical Facts/` workspace folder) stays alive as fallback.
 *
 * Hybrid switchover policy (D-K2):
 *   - Tenant has 0 rows here → folder-driven blob path runs (Iota
 *     behavior preserved).
 *   - Tenant has ≥1 row here → table-driven blob rebuild on every
 *     mutation; folder path is skipped.
 *
 * Severity (D-K3 ordering at write time, surfaced in CRUD UI):
 *   critical > high > medium > low.
 *   Memory V1's render only emits the concatenated blob — severity is
 *   metadata for operators; LLMs see flat facts in priority order.
 *
 * version: monotonic per-fact counter bumped on each PATCH. NOT to be
 * confused with `clients.canonical_facts_revision` which is the
 * tenant-wide cache invalidation key on the read side.
 *
 * is_active: soft-delete flag. DELETE endpoints set false rather than
 * removing rows — preserves audit lineage. Inactive rows do not
 * contribute to the blob.
 */

import {
  pgTable,
  uuid,
  text,
  integer,
  boolean,
  timestamp,
} from "drizzle-orm/pg-core";

import { clients } from "./clients";
import { users } from "./users";

export const canonicalFacts = pgTable("canonical_facts", {
  id: uuid("id").primaryKey().defaultRandom(),
  clientId: uuid("client_id")
    .notNull()
    .references(() => clients.id, { onDelete: "cascade" }),
  /**
   * D-K3 severity vocabulary (CHECK constraint enforced in migration
   * 0026 SQL — Drizzle pg-core does not model CHECK constraints
   * declaratively).
   */
  severity: text("severity").notNull(),
  version: integer("version").notNull().default(1),
  authoredByUserId: uuid("authored_by_user_id").references(
    () => users.id,
    { onDelete: "set null" },
  ),
  body: text("body").notNull(),
  isActive: boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
