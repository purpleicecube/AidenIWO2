-- Loop CAP-A Φ.0b — broaden `output_package_kind` enum
--
-- Adds six new concrete delivery-target kinds so the branded-chain
-- orchestrator (Loops CAP-B → CAP-G) can produce typed output
-- packages for sandbox-local HTML / DOCX / MD renders and for the
-- three design-input HTML render lanes (Stitch / Figma / 21st-Magic).
--
-- Existing 11 values untouched. Strictly additive.
--
-- Architectural locks honored:
--   D5    — `output_surface_routes` registry (CAP-E / Φ.7) maps
--           `(output_kind × is_branded × design_input_source)` to a
--           chain template. The new package-kind values are the
--           *delivery target* axis those routes resolve to.
--   ADR-016 — TS/Python parity preserved.
--
-- Dependencies: 0004_loop3_phase2_output_adapters.sql (introduced
-- the `output_package_kind` enum with the original 11 values).

ALTER TYPE "output_package_kind" ADD VALUE IF NOT EXISTS 'sandbox_html';
--> statement-breakpoint

ALTER TYPE "output_package_kind" ADD VALUE IF NOT EXISTS 'sandbox_docx';
--> statement-breakpoint

ALTER TYPE "output_package_kind" ADD VALUE IF NOT EXISTS 'sandbox_md';
--> statement-breakpoint

ALTER TYPE "output_package_kind" ADD VALUE IF NOT EXISTS 'stitch_html_render';
--> statement-breakpoint

ALTER TYPE "output_package_kind" ADD VALUE IF NOT EXISTS 'figma_html_render';
--> statement-breakpoint

ALTER TYPE "output_package_kind" ADD VALUE IF NOT EXISTS 'twentyfirst_html_render';
