import {
  pgTable,
  uuid,
  varchar,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";

// Loop 9 Phase 9.3 — LLM bindings live in the separate `llm_configs`
// table (see `db/schema/llm_configs.ts`) keyed by (client, agent_role).
// prompt_profiles stay focused on prompt content + scope; the runtime
// joins llm_configs at call time.

export const promptProfileScopeEnum = pgEnum("prompt_profile_scope", [
  "client",
  "workflow",
  "wo",
]);

export const promptProfileStatusEnum = pgEnum("prompt_profile_status", [
  "active",
  "archived",
]);

export const promptProfiles = pgTable(
  "prompt_profiles",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    profileKey: varchar("profile_key", { length: 128 }).notNull(),
    displayName: varchar("display_name", { length: 256 }).notNull(),
    scope: promptProfileScopeEnum("scope").notNull().default("client"),
    status: promptProfileStatusEnum("status").notNull().default("active"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientKey: unique("prompt_profiles_client_key_uniq").on(
      t.clientId,
      t.profileKey
    ),
  })
);

export type PromptProfile = typeof promptProfiles.$inferSelect;
export type NewPromptProfile = typeof promptProfiles.$inferInsert;
