/**
 * Loop CAP-A Φ.1 — `client_brand_profiles` table.
 *
 * One row per tenant. Carries every brand-fact the orchestration spine
 * (Loops CAP-B → CAP-G) reads when:
 *   - Aiden Tier 1 detects branded intent (CAP-E / Φ.8) via `brand_terms`
 *   - Dispatch-time grounding pre-fetches tenant truth (CAP-B / Φ.3)
 *     into the `client_grounding` memory source (SOURCE_PRIORITY slot 0)
 *   - Mark sub-agent writes a content brief (CAP-C / Φ.4) keyed to
 *     `voice_brief` + `icp_summary` + `palette_json` + `fonts_json`
 *   - Darla brand QA gate scores rendered output (CAP-D / Φ.6)
 *   - Paul intelligent delivery picks template variant + adapter
 *     fallback (CAP-D / Φ.5) via `template_handles_json`
 *
 * `template_handles_json` is keyed by `template_profiles.output_kind`
 * value (broadened in Φ.0a / migration 0029 to include html/docx/md).
 * Each value is a LIST of `template_profile_id` UUIDs — multi-template
 * tenants (D-11 / D14) carry >1 entry per kind; single-template
 * tenants carry exactly 1.
 *
 * `design_input_sources_json` carries which design-input MCP adapters
 * (Stitch / Figma / 21st-Magic) the tenant uses for HTML render lanes,
 * and which is the default if intent is ambiguous.
 *
 * `brand_terms` is the keyword set Aiden Tier 1 (CAP-E / Φ.8)
 * deterministic detector matches against intake text.
 *
 * `revision` is monotonic. Bumped on every write. Audited via
 * `client.brand_profile_revision_bumped` (CAP-A LOOP_CAP_A_AUDIT_EVENTS).
 *
 * `requires_brand_qa` per-tenant gate for the Darla checkpoint —
 * defaults true (P4 lock) but can be flipped for tenants whose
 * brand profile is intentionally minimal (e.g. FF.AI skeleton seed
 * before brand assets land — see Q-PG-7 disposition).
 *
 * RLS posture: ENABLE + FORCE + canonical `nullif()::uuid` GUC cast
 * per ADR-014. iwo3_app has SELECT/INSERT/UPDATE/DELETE.
 *
 * UNIQUE (client_id) — exactly one current brand profile per tenant.
 */

import {
  pgTable,
  uuid,
  text,
  integer,
  boolean,
  jsonb,
  timestamp,
  unique,
  index,
} from "drizzle-orm/pg-core";

import { clients } from "./clients";
import { artifacts } from "./artifacts";

export const clientBrandProfiles = pgTable(
  "client_brand_profiles",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "cascade" }),
    paletteJson: jsonb("palette_json").notNull().default({}),
    fontsJson: jsonb("fonts_json").notNull().default({}),
    logoArtifactId: uuid("logo_artifact_id").references(
      () => artifacts.id,
      { onDelete: "set null" },
    ),
    voiceBrief: text("voice_brief"),
    icpSummary: text("icp_summary"),
    requiresBrandQa: boolean("requires_brand_qa").notNull().default(true),
    templateHandlesJson: jsonb("template_handles_json").notNull().default({}),
    designInputSourcesJson: jsonb("design_input_sources_json")
      .notNull()
      .default({}),
    /**
     * brand_terms — text[] in Postgres. Drizzle pg-core models
     * arrays via `.array()` modifier on the underlying scalar type.
     */
    brandTerms: text("brand_terms").array().notNull().default([]),
    revision: integer("revision").notNull().default(1),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClient: unique("client_brand_profiles_client_id_uniq").on(t.clientId),
    clientIdx: index("client_brand_profiles_client_id_idx").on(t.clientId),
  }),
);

export type ClientBrandProfile = typeof clientBrandProfiles.$inferSelect;
export type NewClientBrandProfile = typeof clientBrandProfiles.$inferInsert;
