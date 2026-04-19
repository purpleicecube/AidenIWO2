import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  timestamp,
  index,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";

export const promptRenderedSnapshots = pgTable(
  "prompt_rendered_snapshots",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    correlationId: varchar("correlation_id", { length: 128 }).notNull(),
    layerIds: jsonb("layer_ids").notNull(),
    renderedText: text("rendered_text").notNull(),
    renderHash: varchar("render_hash", { length: 64 }).notNull(),
    overrideRef: jsonb("override_ref"),
    renderedAt: timestamp("rendered_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    idxClientCorr: index("prompt_snapshots_client_corr_idx").on(
      t.clientId,
      t.correlationId
    ),
    idxHash: index("prompt_snapshots_hash_idx").on(t.renderHash),
  })
);

export type PromptRenderedSnapshot =
  typeof promptRenderedSnapshots.$inferSelect;
export type NewPromptRenderedSnapshot =
  typeof promptRenderedSnapshots.$inferInsert;
