-- Loop CAP-A Φ.1 — `client_brand_profiles` table.
--
-- One row per `client_id` (enforced by UNIQUE constraint). Carries
-- every brand-fact the orchestration spine (Loops CAP-B → CAP-G)
-- reads when (a) Aiden Tier 1 detects branded intent (CAP-E / Φ.8),
-- (b) dispatch-time grounding pre-fetches tenant truth (CAP-B / Φ.3),
-- (c) Mark sub-agent writes a content brief (CAP-C / Φ.4),
-- (d) Darla brand QA gate scores rendered output (CAP-D / Φ.6),
-- (e) Paul intelligent delivery picks template variant + adapter
--     fallback (CAP-D / Φ.5).
--
-- Architectural locks honored (per IWO3_ORCHESTRATION_CAP_OUTPUT_SURFACES_v0.3.0):
--   D2    — new table (separation of concerns; revision-tracked
--           jsonb-heavy row is poor fit for `clients` extension).
--   D6    — `client_grounding` source kind (CAP-B / Φ.3) reads from
--           this table at SOURCE_PRIORITY slot 0, above canonical_facts.
--   ADR-014 — RLS canonical pattern with nullif()::uuid GUC cast +
--           FORCE row level security + iwo3_app GRANT.
--
-- Column shapes (jsonb-heavy on purpose — schemas tighten when
-- adapters land in CAP-F / Φ.9 and cement what they need):
--
--   palette_json
--     {"primary": "#8B49E2", "secondary": "#091C53", "accent": "#A61CC8",
--      "neutrals": {"bg": "#F3F4FA", "text": "#0A0A0A"}, ...}
--
--   fonts_json
--     {"heading": "Lexend SemiBold", "body": "Barlow Regular",
--      "fallbacks": ["Arial", "Helvetica", "sans-serif"]}
--
--   template_handles_json
--     {"pptx": ["00000000-0000-4000-8000-000010000001", ...],
--      "pdf":  ["00000000-0000-4000-8000-000010000002", ...],
--      "html": [...], "docx": [...], "md": [...]}
--     LIST per kind — supports multi-template tenants (D-11 / D14).
--
--   design_input_sources_json
--     {"stitch": true, "figma": false, "twentyfirst": true,
--      "default_for_html": "stitch"}
--
--   brand_terms (text[])
--     ["Klear.ai", "klear ai", "Klear", "Klear AI", ...]
--     keywords Aiden Tier 1 (CAP-E / Φ.8) detector matches against
--     intake text to decide is_branded_request.
--
-- Dependencies: migration 0019 (artifacts table — fk for logo).
--               canonical_facts at migration 0026 — coexists, not
--               replaced; brand_profiles is curated brand truth,
--               canonical_facts is correctional.

CREATE TABLE IF NOT EXISTS "client_brand_profiles" (
    "id"                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "client_id"                   uuid NOT NULL,
    "palette_json"                jsonb NOT NULL DEFAULT '{}'::jsonb,
    "fonts_json"                  jsonb NOT NULL DEFAULT '{}'::jsonb,
    "logo_artifact_id"            uuid,
    "voice_brief"                 text,
    "icp_summary"                 text,
    "requires_brand_qa"           boolean NOT NULL DEFAULT true,
    "template_handles_json"       jsonb NOT NULL DEFAULT '{}'::jsonb,
    "design_input_sources_json"   jsonb NOT NULL DEFAULT '{}'::jsonb,
    "brand_terms"                 text[] NOT NULL DEFAULT ARRAY[]::text[],
    "revision"                    integer NOT NULL DEFAULT 1,
    "created_at"                  timestamp with time zone NOT NULL DEFAULT now(),
    "updated_at"                  timestamp with time zone NOT NULL DEFAULT now()
);
--> statement-breakpoint

ALTER TABLE "client_brand_profiles"
  ADD CONSTRAINT "client_brand_profiles_client_id_clients_id_fk"
    FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id")
    ON DELETE CASCADE;
--> statement-breakpoint

ALTER TABLE "client_brand_profiles"
  ADD CONSTRAINT "client_brand_profiles_logo_artifact_id_artifacts_id_fk"
    FOREIGN KEY ("logo_artifact_id") REFERENCES "public"."artifacts"("id")
    ON DELETE SET NULL;
--> statement-breakpoint

-- One row per tenant. Multi-row tenant brand history (if needed
-- later) lives in a separate revision-history table; this row is
-- the current truth.
ALTER TABLE "client_brand_profiles"
  ADD CONSTRAINT "client_brand_profiles_client_id_uniq"
    UNIQUE ("client_id");
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "client_brand_profiles_client_id_idx"
  ON "client_brand_profiles" ("client_id");
--> statement-breakpoint

-- ── RLS tenant isolation (ADR-014 §Q4 keep_both posture) ──────────
ALTER TABLE "client_brand_profiles" ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint

ALTER TABLE "client_brand_profiles" FORCE ROW LEVEL SECURITY;
--> statement-breakpoint

CREATE POLICY "client_brand_profiles_tenant_iso" ON "client_brand_profiles" FOR ALL
    USING ("client_id" = nullif(current_setting('app.current_client_id', true), '')::uuid)
    WITH CHECK ("client_id" = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

-- ── Grant baseline access to iwo3_app role ────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON "client_brand_profiles" TO "iwo3_app";
