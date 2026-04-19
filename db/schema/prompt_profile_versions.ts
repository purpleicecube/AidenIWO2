import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { promptProfiles } from "./prompt_profiles";
import { users } from "./users";

export const promptVersionStatusEnum = pgEnum("prompt_version_status", [
  "draft",
  "published",
  "deprecated",
]);

export const promptProfileVersions = pgTable(
  "prompt_profile_versions",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    profileId: uuid("profile_id")
      .notNull()
      .references(() => promptProfiles.id, { onDelete: "restrict" }),
    version: varchar("version", { length: 32 }).notNull(),
    basePrompt: text("base_prompt").notNull(),
    constraints: jsonb("constraints"),
    authoredByUserId: uuid("authored_by_user_id")
      .notNull()
      .references(() => users.id, { onDelete: "restrict" }),
    status: promptVersionStatusEnum("status").notNull().default("draft"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    publishedAt: timestamp("published_at", { withTimezone: true }),
  },
  (t) => ({
    uniqProfileVersion: unique("prompt_profile_versions_profile_version_uniq").on(
      t.profileId,
      t.version
    ),
  })
);

export type PromptProfileVersion = typeof promptProfileVersions.$inferSelect;
export type NewPromptProfileVersion = typeof promptProfileVersions.$inferInsert;
