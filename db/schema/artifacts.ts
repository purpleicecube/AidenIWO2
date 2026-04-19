import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  timestamp,
  pgEnum,
  index,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";

export const artifactSourceTypeEnum = pgEnum("artifact_source_type", [
  "upload",
  "generated",
  "imported",
]);

export const artifactContentClassEnum = pgEnum("artifact_content_class", [
  "c0",
  "c1",
  "c2",
  "c3",
]);

export const artifacts = pgTable(
  "artifacts",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    sourceType: artifactSourceTypeEnum("source_type").notNull(),
    contentClass: artifactContentClassEnum("content_class").notNull(),
    mimeType: varchar("mime_type", { length: 128 }),
    filename: varchar("filename", { length: 512 }),
    storageRef: varchar("storage_ref", { length: 1024 }).notNull(),
    extractedText: text("extracted_text"),
    metadata: jsonb("metadata"),
    createdByUserId: uuid("created_by_user_id")
      .notNull()
      .references(() => users.id, { onDelete: "restrict" }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    idxClientCreated: index("artifacts_client_created_idx").on(
      t.clientId,
      t.createdAt
    ),
  })
);

export type Artifact = typeof artifacts.$inferSelect;
export type NewArtifact = typeof artifacts.$inferInsert;
