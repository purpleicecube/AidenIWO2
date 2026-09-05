-- Make `md` and `html` requestable output kinds.
--
-- FOUND BY END-TO-END TEST, 2026-09-05. `POST /work_orders` rejects any
-- output_kind with no published template for the tenant
-- (`no_published_template_for_output_kind`, HTTP 422). Probing all six
-- kinds showed only `pdf` and `pptx` were accepted — `md`, `html`,
-- `docx` and `generic` all 422'd. The operator's stated need is "an MD
-- file, a PDF, or even a self-contained HTML"; two of those three could
-- not be asked for at all.
--
-- SCOPE OF THIS MIGRATION — READ BEFORE ASSUMING MD/HTML WORK END-TO-END.
--
-- This migration closes TWO things only:
--   1. request admission — `POST /work_orders` no longer 422s on
--      output_kind `md` / `html`;
--   2. template-profile availability — a local profile now exists for
--      each, per tenant, naming a real engine.
--
-- It does NOT make MD or HTML deliverable. The local renderers
-- (`adapter/sandbox_renderers.py`) exist and `output_surface_routes`
-- already routes md → sandbox_md and html → sandbox_html, but the
-- delivery path is still Gamma-shaped. Gaps remaining, owned by
-- Omicron.10:
--
--   * deterministic package kind — the Tier-2 envelope contract offers
--     only `gamma_pptx | gamma_pdf | generic`, and the validator
--     allow-list coerces anything else to `generic`, so a requested
--     `md`/`html` kind does not survive into the output package;
--   * universal adapter dispatch — direct work-order code auto-
--     dispatches only `gamma_*` packages; direct and workflow paths
--     must converge on `output_surface_routes` + `dispatch_for_adapter()`
--     with the selected template as the deterministic authority;
--   * HTML MIME and extension — local HTML currently defaults to
--     Markdown MIME and a `.md` extension at initial filing;
--   * canonical artifact location — the rendered artifact must land in
--     the dated `Outputs/<date>/<order-slug>_<id8>/` hierarchy;
--   * duplicate-artifact prevention — sandbox renderers currently
--     create a second artifact under `Branded Outputs`, so one work
--     order can yield two artifacts for one deliverable.
--
-- Until Omicron.10 lands, `md` and `html` are REQUESTABLE but not
-- PRODUCIBLE, and a request for either still returns a Gamma PDF.
--
-- `sandbox_pdf` and `sandbox_docx` are deliberately NOT given profiles
-- here: both renderers are stubs that emit `adapter_unavailable`
-- (CR-013). Publishing a template for a stub would turn a clear 422 at
-- submit time into a failed work order later, which is worse.

ALTER TYPE render_engine ADD VALUE IF NOT EXISTS 'sandbox_md';
--> statement-breakpoint

ALTER TYPE render_engine ADD VALUE IF NOT EXISTS 'sandbox_html';
--> statement-breakpoint

-- Local, brand-aware, no external service. `fidelity_required = false`
-- and `fallback_policy = 'none'`: these ARE the local path, so there is
-- nothing to fall back to and no fidelity contract with a third party.
INSERT INTO template_profiles
  (id, client_id, profile_key, output_kind, engine, external_ref,
   fidelity_required, fallback_policy, content_contract, status)
SELECT
  gen_random_uuid(), c.id,
  'local_md_' || lower(replace(c.display_name, '.', '_')),
  'md', 'sandbox_md', NULL, false, 'none',
  jsonb_build_object('label', 'Local Markdown (stdlib, brand frontmatter)'),
  'active'
FROM clients c
WHERE NOT EXISTS (
  SELECT 1 FROM template_profiles tp
   WHERE tp.client_id = c.id AND tp.output_kind = 'md'
);
--> statement-breakpoint

INSERT INTO template_profiles
  (id, client_id, profile_key, output_kind, engine, external_ref,
   fidelity_required, fallback_policy, content_contract, status)
SELECT
  gen_random_uuid(), c.id,
  'local_html_' || lower(replace(c.display_name, '.', '_')),
  'html', 'sandbox_html', NULL, false, 'none',
  jsonb_build_object('label', 'Local self-contained HTML (brand palette + fonts)'),
  'active'
FROM clients c
WHERE NOT EXISTS (
  SELECT 1 FROM template_profiles tp
   WHERE tp.client_id = c.id AND tp.output_kind = 'html'
);
