-- Loop CAP-A Φ.0a — broaden `template_profiles.output_kind` enum
--
-- Adds three new abstract format intents (`html`, `docx`, `md`) so the
-- branded-chain orchestrator (Loops CAP-B → CAP-G) can route HTML
-- landing-page, DOCX, and MD requests through the same template-profile
-- machinery that already serves PPTX and PDF.
--
-- This is a strictly additive enum extension — existing rows retain
-- their `pptx | pdf | other` values; no data migration required.
--
-- Architectural locks honored (per IWO3_ORCHESTRATION_CAP_OUTPUT_SURFACES_v0.3.0):
--   D11   — `requested_outputs.output_kind` stays bound to this enum;
--           no new normalized routing enum introduced.
--   D13   — extend the narrow live enum rather than promoting
--           `requested_outputs` to a multi-row table.
--   ADR-016 — TS/Python parity preserved (snapshot + Python mirror
--           updated in the same commit; enum-parity test enforces).
--
-- Dependencies: none beyond the existing 0001_mature_darwin migration
-- that introduced the `output_kind` enum for `template_profiles`.

ALTER TYPE "output_kind" ADD VALUE IF NOT EXISTS 'html';
--> statement-breakpoint

ALTER TYPE "output_kind" ADD VALUE IF NOT EXISTS 'docx';
--> statement-breakpoint

ALTER TYPE "output_kind" ADD VALUE IF NOT EXISTS 'md';
