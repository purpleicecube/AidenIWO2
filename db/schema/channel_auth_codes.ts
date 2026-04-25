import {
  pgTable,
  uuid,
  varchar,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";
import { channelKindEnum } from "./channel_identities";

/**
 * MegaLoop Alpha α.5 — one-time channel auth codes.
 *
 * Operator generates a code via `POST /channel/auth_codes`; passes the
 * code through the channel (e.g. Telegram `/start CODE`); the channel
 * adapter consumes the code and inserts a `channel_identities` row.
 *
 * Codes expire (default 15 min) and are consumable exactly once.
 *
 * Per Stage A § B7. Multi-tenant via client_id + RLS.
 */
export const channelAuthCodeStatusEnum = pgEnum(
  "channel_auth_code_status",
  ["pending", "consumed", "expired", "revoked"]
);

export const channelAuthCodes = pgTable(
  "channel_auth_codes",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    code: varchar("code", { length: 64 }).notNull(),
    channelKind: channelKindEnum("channel_kind").notNull(),
    issuedByUserId: uuid("issued_by_user_id")
      .notNull()
      .references(() => users.id, { onDelete: "restrict" }),
    status: channelAuthCodeStatusEnum("status").notNull().default("pending"),
    consumedExternalId: varchar("consumed_external_id", { length: 256 }),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    consumedAt: timestamp("consumed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqCode: unique("channel_auth_codes_code_uniq").on(t.code),
  })
);

export type ChannelAuthCode = typeof channelAuthCodes.$inferSelect;
export type NewChannelAuthCode = typeof channelAuthCodes.$inferInsert;
