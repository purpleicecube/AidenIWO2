import {
  pgTable,
  uuid,
  varchar,
  timestamp,
  boolean,
  jsonb,
  pgEnum,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";

export const outputKindEnum = pgEnum("output_kind", ["pptx", "pdf", "other"]);

export const renderEngineEnum = pgEnum("render_engine", [
  "gamma",
  "gamma_basic",
  "sandbox_pptx",
  "sandbox_pdf",
  "designlab",
]);

export const fallbackPolicyEnum = pgEnum("fallback_policy", [
  "none",
  "allowed_with_approval",
  "allowed",
]);

export const templateProfileStatusEnum = pgEnum("template_profile_status", [
  "active",
  "archived",
]);

export const templateProfiles = pgTable(
  "template_profiles",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    profileKey: varchar("profile_key", { length: 128 }).notNull(),
    outputKind: outputKindEnum("output_kind").notNull(),
    engine: renderEngineEnum("engine").notNull(),
    externalRef: varchar("external_ref", { length: 256 }),
    fidelityRequired: boolean("fidelity_required").notNull().default(true),
    fallbackPolicy: fallbackPolicyEnum("fallback_policy")
      .notNull()
      .default("none"),
    contentContract: jsonb("content_contract"),
    status: templateProfileStatusEnum("status").notNull().default("active"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientProfile: unique("template_profiles_client_key_uniq").on(
      t.clientId,
      t.profileKey
    ),
  })
);

export type TemplateProfile = typeof templateProfiles.$inferSelect;
export type NewTemplateProfile = typeof templateProfiles.$inferInsert;
