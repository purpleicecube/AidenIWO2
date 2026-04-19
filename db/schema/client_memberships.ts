import {
  pgTable,
  uuid,
  timestamp,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";

export const membershipRoleEnum = pgEnum("membership_role", [
  "owner",
  "admin",
  "operator",
  "reviewer",
  "viewer",
  "agent_system",
]);

export const membershipStatusEnum = pgEnum("membership_status", [
  "active",
  "revoked",
]);

export const clientMemberships = pgTable(
  "client_memberships",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "restrict" }),
    role: membershipRoleEnum("role").notNull(),
    status: membershipStatusEnum("status").notNull().default("active"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientUser: unique("client_memberships_client_user_uniq").on(
      t.clientId,
      t.userId
    ),
  })
);

export type ClientMembership = typeof clientMemberships.$inferSelect;
export type NewClientMembership = typeof clientMemberships.$inferInsert;
