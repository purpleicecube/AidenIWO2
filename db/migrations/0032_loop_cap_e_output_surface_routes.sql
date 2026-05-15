-- Loop CAP-E Φ.7 — `output_surface_routes` registry table.
--
-- Global (tenant-agnostic) registry mapping
--   (output_kind, is_branded, design_input_source) → workflow_key + adapter chain
-- so dispatch.py + Aiden Tier 1 read chain selection from a single
-- typed source rather than from inline if/else mappings scattered
-- across the runtime.
--
-- Per-tenant chains are still tenant-scoped — `workflow_key` is the
-- shared chain identifier, and the actual workflow_template version
-- the runtime executes is resolved per-(client_id, key) at dispatch
-- time via the existing `workflows` table lookup.
--
-- Architectural locks honored:
--   D5    — new table chosen over `adapter_catalog + workflow_templates`
--           join (cleanest separation; small global-scope; no RLS).
--   P6    — output kind taxonomy drives chain selection from the live
--           contract surface (`requested_outputs.output_kind`).
--   P7    — Aiden Tier 1 reads from this registry in CAP-E Φ.8 to
--           emit `decision_kind="workflow_brief"` with the matching
--           `workflow_key`.
--
-- Tenant scope:
--   No FORCE RLS. The registry is global by design — chain identifiers
--   are shared across tenants; what differs per-tenant is which
--   workflows + workflow_templates rows actually exist with a given
--   key. Lookups in dispatch carry the tenant `client_id` against
--   `workflows`, not against this registry.
--
-- Dependencies: 0029 (broadened template_profiles.output_kind enum,
-- which template_handles_json keys map onto), 0031 (client_brand_profiles).

CREATE TABLE IF NOT EXISTS "output_surface_routes" (
    "id"                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "output_kind"              text NOT NULL,
    "is_branded"               boolean NOT NULL,
    "design_input_source"      text,
    "workflow_key"             text NOT NULL,
    "primary_adapter_key"      text NOT NULL,
    "fallback_adapter_keys"    text[] NOT NULL DEFAULT ARRAY[]::text[],
    "notes"                    text,
    "created_at"               timestamp with time zone NOT NULL DEFAULT now(),
    "updated_at"               timestamp with time zone NOT NULL DEFAULT now()
);
--> statement-breakpoint

-- One route per (output_kind, is_branded, design_input_source) tuple.
-- COALESCE on the nullable design_input_source so the unique constraint
-- treats NULL as a single value (Postgres default treats NULLs as
-- distinct, which is wrong for our routing semantics).
CREATE UNIQUE INDEX IF NOT EXISTS "output_surface_routes_unique_tuple_idx"
  ON "output_surface_routes" (
    "output_kind",
    "is_branded",
    COALESCE("design_input_source", 'none')
  );
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "output_surface_routes_lookup_idx"
  ON "output_surface_routes" ("output_kind", "is_branded");
--> statement-breakpoint

-- Grant baseline access to iwo3_app role. No FORCE RLS — global registry.
GRANT SELECT ON "output_surface_routes" TO "iwo3_app";
