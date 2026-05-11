-- 0028 — sandbox_sessions internal operator utility (Path A-prime, 2026-05-11)
--
-- Sandbox Operational Darkmode (ADR-035): the IWO2-inherited Node
-- sandbox path requires this table to exist in IWO3. The IWO2-era
-- schema is *global* (no client_id) — explicitly an operator power-
-- user utility, not a tenant-scoped product surface.
--
-- Path A-prime decision (per CODEX 2026-05-11): migrate as-is WITHOUT
-- client_id or FORCE RLS, BUT pair with route-level creator-or-admin
-- gating on the Node side so cross-tenant leakage is bounded by the
-- session's `created_by` field rather than by RLS. Tenancy-aware
-- sandbox (Path B with client_id + RLS + auth bridge) is a follow-on
-- loop documented in ADR-035 §Successor.
--
-- Deliberate non-RLS posture documented inline below so future
-- contributors don't grep "sandbox_sessions" and conclude RLS was
-- forgotten. Migration-source-manifest registration in
-- infra/local/manifest-populate.ts marks this table with a notes
-- field that names ADR-035 + the carve-out.
--
-- Schema mirrors shared/schema.ts:918 exactly so the IWO2-inherited
-- Express/React surface boots without further surgery.

CREATE TABLE IF NOT EXISTS sandbox_sessions (
  id          varchar PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text         NOT NULL,
  description text,
  status      text         NOT NULL DEFAULT 'active',
  environment jsonb        DEFAULT '{}'::jsonb,
  logs        jsonb        DEFAULT '[]'::jsonb,
  result      jsonb,
  created_by  text         DEFAULT 'system',
  started_at  timestamp    DEFAULT now(),
  completed_at timestamp,
  created_at  timestamp    NOT NULL DEFAULT now(),
  updated_at  timestamp    NOT NULL DEFAULT now()
);

-- Indexes the Node app's typical access pattern needs:
--   • list-by-creator (Path A-prime gate)
--   • list-by-status (the React UI's status filter)
CREATE INDEX IF NOT EXISTS sandbox_sessions_created_by_idx
  ON sandbox_sessions (created_by);
CREATE INDEX IF NOT EXISTS sandbox_sessions_status_created_at_idx
  ON sandbox_sessions (status, created_at DESC);

-- NOTE: RLS is intentionally NOT enabled on this table. Sandbox
-- visibility/mutation is gated at the Node route layer
-- (server/routes.ts §"Sandbox Session Routes") by creator-or-admin
-- check against the authenticated user. ADR-035 §Tenancy carve-out
-- records this decision and its expiration trigger (the follow-on
-- Path B loop).

GRANT SELECT, INSERT, UPDATE, DELETE ON sandbox_sessions TO iwo3_app;
