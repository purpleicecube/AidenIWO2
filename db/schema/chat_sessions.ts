import {
  pgTable,
  uuid,
  jsonb,
  timestamp,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";

/**
 * MegaLoop Beta-1 ε.1 — operator-facing cross-session chat persistence.
 *
 * Architect Q7 lock: each (user_id, client_id) pair has exactly one
 * chat session row. Message history + chat-context (recent
 * created WO id / output package id / etc.) live in JSONB for shape
 * flexibility during Beta-1; if the structure stabilises we can
 * promote individual columns in Beta-2 without breaking the API.
 *
 * Boundary (architect): this carries operator chat continuity, not
 * agent-side cross-WO Munninn-style memory.
 */
export const chatSessions = pgTable(
  "chat_sessions",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "cascade" }),
    /** Append-only operator + assistant turns. Latest at the end. */
    messages: jsonb("messages").notNull().default([]),
    /** Current chat context (last_work_order_id / last_output_package_id / etc). */
    context: jsonb("context").notNull().default({}),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqUserClient: unique("chat_sessions_user_client_uniq").on(
      t.userId,
      t.clientId
    ),
  })
);

export type ChatSession = typeof chatSessions.$inferSelect;
export type NewChatSession = typeof chatSessions.$inferInsert;
