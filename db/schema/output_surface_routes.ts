/**
 * Loop CAP-E Φ.7 — `output_surface_routes` registry.
 *
 * Global (tenant-agnostic) routing registry mapping
 *   (output_kind, is_branded, design_input_source) → workflow_key +
 *   primary adapter + fallback adapter chain
 *
 * Dispatch + Aiden Tier 1 read chain selection from this registry
 * (CAP-E Φ.8) instead of from inline if/else mappings. Chains
 * themselves are tenant-scoped (per-(client_id, key) workflows row);
 * this registry holds only the shared selection logic.
 *
 * No FORCE RLS — registry is global by design. Dispatch carries
 * tenant `client_id` against the `workflows` table at lookup time.
 *
 * Unique constraint on (output_kind, is_branded, COALESCE(design_input_source, 'none'))
 * is enforced by a raw-SQL index in migration 0032 because Postgres
 * treats NULL as distinct in unique constraints by default — wrong
 * for our routing semantics where NULL design_input_source means
 * "no design input" and is a single tuple.
 */

import {
  pgTable,
  uuid,
  text,
  boolean,
  timestamp,
  index,
} from "drizzle-orm/pg-core";

export const outputSurfaceRoutes = pgTable(
  "output_surface_routes",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    outputKind: text("output_kind").notNull(),
    isBranded: boolean("is_branded").notNull(),
    designInputSource: text("design_input_source"),
    workflowKey: text("workflow_key").notNull(),
    primaryAdapterKey: text("primary_adapter_key").notNull(),
    fallbackAdapterKeys: text("fallback_adapter_keys")
      .array()
      .notNull()
      .default([]),
    notes: text("notes"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    lookupIdx: index("output_surface_routes_lookup_idx").on(
      t.outputKind,
      t.isBranded,
    ),
  }),
);

export type OutputSurfaceRoute = typeof outputSurfaceRoutes.$inferSelect;
export type NewOutputSurfaceRoute = typeof outputSurfaceRoutes.$inferInsert;
