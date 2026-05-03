/**
 * MegaLoop Theta — tool discovery metadata (tool_tags + assignments).
 *
 * Two narrow tables that sit beside `tool_catalog`. They let the Tools
 * Locker UI group/filter tools by free-form tags (e.g. "klear",
 * "design", "tier2", "experimental"). Tag CRUD UI is deferred per the
 * scope record; the schema lands now so subsequent loops do not need a
 * fresh migration.
 *
 * `tool_tags`        — flat tag dictionary (unique name).
 * `tool_tag_assignments` — many-to-many bridge with CASCADE on both FKs
 *                          so deleting a tool or a tag cleans up the
 *                          bridge row automatically.
 */

import {
  pgTable,
  uuid,
  varchar,
  text,
  timestamp,
  unique,
  index,
} from "drizzle-orm/pg-core";
import { toolCatalog } from "./tool_catalog";

export const toolTags = pgTable("tool_tags", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: varchar("name", { length: 64 }).notNull().unique(),
  category: varchar("category", { length: 64 }).notNull().default("general"),
  description: text("description"),
  color: varchar("color", { length: 16 }).default("#6366f1"),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export const toolTagAssignments = pgTable(
  "tool_tag_assignments",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    toolCatalogId: uuid("tool_catalog_id")
      .notNull()
      .references(() => toolCatalog.id, { onDelete: "cascade" }),
    tagId: uuid("tag_id")
      .notNull()
      .references(() => toolTags.id, { onDelete: "cascade" }),
    assignedAt: timestamp("assigned_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqAssignment: unique("tool_tag_assignments_unique").on(
      t.toolCatalogId,
      t.tagId
    ),
    toolIdx: index("tool_tag_assignments_tool_idx").on(t.toolCatalogId),
    tagIdx: index("tool_tag_assignments_tag_idx").on(t.tagId),
  })
);

export type ToolTagRow = typeof toolTags.$inferSelect;
export type NewToolTagRow = typeof toolTags.$inferInsert;
export type ToolTagAssignmentRow = typeof toolTagAssignments.$inferSelect;
export type NewToolTagAssignmentRow = typeof toolTagAssignments.$inferInsert;
