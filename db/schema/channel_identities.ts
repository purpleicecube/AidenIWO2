import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  timestamp,
  pgEnum,
  unique,
  index,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";

/**
 * MegaLoop Alpha α.5 — channel identity bindings.
 *
 * Binds an external channel principal (Telegram chat_id, future Slack
 * user_id, etc.) to an IWO3 (client_id, user_id) pair. Without an
 * active binding, channel actions are refused.
 *
 * Established via the `/start <auth_code>` flow:
 *   1. Operator generates a one-time auth code in Aiden Settings
 *      (POST /channel/auth_codes) — code stored in channel_auth_codes.
 *   2. Operator sends `/start CODE` to the bot.
 *   3. Bot looks up the code, marks it consumed, inserts a row here.
 *   4. Subsequent inbound messages from that chat_id are bound and
 *      pass RBAC against the bound user's permissions.
 *
 * Per Stage A § B4 + § B7. Multi-tenant via client_id + RLS.
 */
export const channelKindEnum = pgEnum("channel_kind", [
  "telegram",
  "slack",
  "email",
  "sms",
]);

export const channelIdentityStatusEnum = pgEnum(
  "channel_identity_status",
  ["active", "revoked"]
);

export const channelIdentities = pgTable(
  "channel_identities",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    channelKind: channelKindEnum("channel_kind").notNull(),
    externalId: varchar("external_id", { length: 256 }).notNull(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "restrict" }),
    status: channelIdentityStatusEnum("status").notNull().default("active"),
    metadata: jsonb("metadata"),
    boundAt: timestamp("bound_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    lastSeenAt: timestamp("last_seen_at", { withTimezone: true }),
    revokedAt: timestamp("revoked_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientChannelExternal: unique(
      "channel_identities_client_channel_external_uniq"
    ).on(t.clientId, t.channelKind, t.externalId),
    idxChannelExternal: index(
      "channel_identities_channel_external_idx"
    ).on(t.channelKind, t.externalId),
  })
);

export type ChannelIdentity = typeof channelIdentities.$inferSelect;
export type NewChannelIdentity = typeof channelIdentities.$inferInsert;
