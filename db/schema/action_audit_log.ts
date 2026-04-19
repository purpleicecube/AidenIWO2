import {
  pgTable,
  bigserial,
  uuid,
  varchar,
  jsonb,
  timestamp,
  index,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";

export const actionAuditLog = pgTable(
  "action_audit_log",
  {
    id: bigserial("id", { mode: "number" }).primaryKey(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    actorUserId: uuid("actor_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    action: varchar("action", { length: 128 }).notNull(),
    targetType: varchar("target_type", { length: 64 }),
    targetId: varchar("target_id", { length: 128 }),
    metadata: jsonb("metadata"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    idxClientCreated: index("action_audit_log_client_created_idx").on(
      t.clientId,
      t.createdAt
    ),
  })
);

export type ActionAuditLogRow = typeof actionAuditLog.$inferSelect;
export type NewActionAuditLogRow = typeof actionAuditLog.$inferInsert;
