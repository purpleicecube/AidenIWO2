import {
  pgTable,
  bigserial,
  uuid,
  varchar,
  jsonb,
  timestamp,
  index,
  primaryKey,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";

/**
 * action_audit_log — privileged-action audit.
 *
 * Partitioning (ADR-010, Phase 1.5): the live table is
 * `PARTITION BY RANGE (created_at)` with monthly partitions. Drizzle does
 * not model partitioning declaratively, so the partitioned structure lives
 * in the raw-SQL migration `db/migrations/0002_partition_action_audit_log.sql`.
 * This schema file describes the column shape only.
 *
 * Primary key is composite `(id, created_at)` because every unique
 * constraint on a partitioned table must include the partition key.
 *
 * If a future `drizzle-kit generate` run surfaces spurious "unpartition"
 * diffs against the live DB, discard them — the partitioning is authoritative
 * in the raw-SQL migration, not in this schema file.
 */
export const actionAuditLog = pgTable(
  "action_audit_log",
  {
    id: bigserial("id", { mode: "number" }).notNull(),
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
    pk: primaryKey({
      name: "action_audit_log_pkey",
      columns: [t.id, t.createdAt],
    }),
    idxClientCreated: index("action_audit_log_client_created_idx").on(
      t.clientId,
      t.createdAt
    ),
  })
);

export type ActionAuditLogRow = typeof actionAuditLog.$inferSelect;
export type NewActionAuditLogRow = typeof actionAuditLog.$inferInsert;
