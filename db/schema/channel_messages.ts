import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  text,
  integer,
  timestamp,
  pgEnum,
  unique,
  index,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { workOrders } from "./work_orders";
import { workflowExecutions } from "./workflow_executions";
import { channelKindEnum, channelIdentities } from "./channel_identities";

/**
 * MegaLoop Alpha α.5 — channel message log + outbox.
 *
 * Single table for both directions:
 *   direction = 'inbound'   — message received from external channel
 *   direction = 'outbound'  — message we want to send back; pending
 *                             rows are the implicit outbox queue
 *
 * Stage A § B5 (full payload stored; redaction policy is Beta) + § B6
 * (at-least-once outbound; idempotency_key prevents accidental dupes).
 *
 * Multi-tenant via client_id + RLS. The 25→27-table tenant-scoped set
 * grows by two with this migration.
 */
export const channelMessageDirectionEnum = pgEnum(
  "channel_message_direction",
  ["inbound", "outbound"]
);

export const channelMessageStatusEnum = pgEnum(
  "channel_message_status",
  ["received", "processed", "failed", "pending", "sent"]
);

export const channelMessages = pgTable(
  "channel_messages",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    channelKind: channelKindEnum("channel_kind").notNull(),
    direction: channelMessageDirectionEnum("direction").notNull(),
    channelIdentityId: uuid("channel_identity_id").references(
      () => channelIdentities.id,
      { onDelete: "set null" }
    ),
    externalMessageId: varchar("external_message_id", { length: 256 }),
    externalChatId: varchar("external_chat_id", { length: 256 }),
    idempotencyKey: varchar("idempotency_key", { length: 256 }),
    payload: jsonb("payload").notNull(),
    intent: varchar("intent", { length: 64 }),
    relatedWorkOrderId: uuid("related_work_order_id").references(
      () => workOrders.id,
      { onDelete: "set null" }
    ),
    relatedWorkflowExecutionId: uuid(
      "related_workflow_execution_id"
    ).references(() => workflowExecutions.id, { onDelete: "set null" }),
    status: channelMessageStatusEnum("status").notNull().default("received"),
    attempts: integer("attempts").notNull().default(0),
    errorDetail: text("error_detail"),
    correlationId: varchar("correlation_id", { length: 128 }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    sentAt: timestamp("sent_at", { withTimezone: true }),
    processedAt: timestamp("processed_at", { withTimezone: true }),
  },
  (t) => ({
    /**
     * Pre-Beta β.5 — chat-scoped inbound UNIQUE. Telegram (and most
     * chat APIs) number message ids per chat, not globally; the prior
     * (channel_kind, external_message_id) scope let chat A's #42 alias
     * onto chat B's #42 in this column. ADR-028 widens to include
     * external_chat_id.
     */
    uniqInboundExternalId: unique(
      "channel_messages_inbound_external_uniq"
    ).on(t.channelKind, t.externalChatId, t.externalMessageId),
    uniqIdempotency: unique("channel_messages_idempotency_uniq").on(
      t.channelKind,
      t.idempotencyKey
    ),
    idxClientStatusCreated: index(
      "channel_messages_client_status_created_idx"
    ).on(t.clientId, t.status, t.createdAt),
    idxOutboxPending: index("channel_messages_outbox_pending_idx").on(
      t.direction,
      t.status,
      t.createdAt
    ),
  })
);

export type ChannelMessage = typeof channelMessages.$inferSelect;
export type NewChannelMessage = typeof channelMessages.$inferInsert;
