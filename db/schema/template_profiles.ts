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

// Loop CAP-A Φ.0a — broadened from {pptx, pdf, other} to add the
// abstract format intents the branded-chain orchestrator (Loops
// CAP-B → CAP-G) needs to route HTML / DOCX / MD requests through
// the same template-profile machinery. Migration 0029.
//
// Ordering follows live DB enumsortorder: the Loop 1 trio ({pptx, pdf,
// other}) keeps its original position; the three additive values land
// at the end. The Python mirror at apps/api-fastapi/contracts/enums.py
// preserves this order; enum-parity test enforces it byte-for-byte.
export const outputKindEnum = pgEnum("output_kind", [
  "pptx",
  "pdf",
  "other",
  "html",
  "docx",
  "md",
]);

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
