-- 0033 — Sandbox β.0 foundation (Sandbox-Hosted-In-App-β.0, 2026-05-17)
--
-- Per ADR-036 + CODEX β.0 brief (WS024 baseline edce652): lays the
-- column + check-constraint foundation for the sandbox acceptance
-- workflow and the tenant cutover. **Does NOT toggle FORCE RLS.**
-- The RLS cutover is a deliberate β.x cutover slice that must land
-- in lockstep with Node-side coexistence work (the Express
-- sandbox routes currently issue queries on an un-tenanted
-- connection per ADR-035 §Tenancy carve-out; flipping FORCE RLS
-- without updating those queries would break the Node sandbox
-- surface today).
--
-- What this migration does:
--   • adds `client_id uuid` NULL — populated on new rows; NULL on
--     legacy rows from the ADR-035 carve-out (preserved through the
--     transition; the β.x cutover will require NOT NULL once all
--     rows have client_id and the Node side passes tenant context)
--   • adds the 5-column acceptance surface
--     (acceptance_state, accepted_by_user_id, accepted_at, review_notes)
--   • acceptance_state CHECK constraint enforces the locked V1
--     state vocabulary (mirrors packages/contracts/sandbox/
--     state_machines.ts SANDBOX_ACCEPTANCE_STATES per D-B2)
--   • indexes on (client_id) and (acceptance_state, client_id) for
--     the rail query patterns anticipated in β.1+
--
-- What this migration deliberately does NOT do (per β.0 brief):
--   • does NOT toggle RLS on sandbox_sessions (β.x cutover handles
--     both the ENABLE + FORCE flip in lockstep with the policy)
--   • does NOT NOT NULL client_id (β.x once backfill posture is set)
--   • does NOT author policies (they live in the cutover slice
--     alongside the Node-side tenant connection)
--   • does NOT touch GRANT statements (existing iwo3_app grants from
--     migration 0028 cover the new columns automatically)
--   • does NOT transition any existing row's acceptance_state (every
--     existing row defaults to 'uploaded' — operators see the legacy
--     sandbox as un-evaluated through the β.1+ acceptance flow)

ALTER TABLE sandbox_sessions
  ADD COLUMN IF NOT EXISTS client_id           uuid,
  ADD COLUMN IF NOT EXISTS acceptance_state    text         NOT NULL DEFAULT 'uploaded',
  ADD COLUMN IF NOT EXISTS accepted_by_user_id varchar,
  ADD COLUMN IF NOT EXISTS accepted_at         timestamptz,
  ADD COLUMN IF NOT EXISTS review_notes        text;

-- acceptance_state vocabulary lock — mirrors the
-- SANDBOX_ACCEPTANCE_STATES export in
-- packages/contracts/sandbox/state_machines.ts. Adding new states
-- requires updating both surfaces in lockstep.
ALTER TABLE sandbox_sessions
  ADD CONSTRAINT sandbox_sessions_acceptance_state_check
  CHECK (acceptance_state IN (
    'uploaded',
    'evaluating',
    'tested',
    'under_review',
    'accepted',
    'rejected',
    'reopened'
  ));

-- Indexes anticipating β.1+ query patterns:
--   • list sandboxes for a tenant (client_id)
--   • list-by-acceptance-state within a tenant (review queue,
--     pending-acceptance queue, etc.)
CREATE INDEX IF NOT EXISTS sandbox_sessions_client_id_idx
  ON sandbox_sessions (client_id);
CREATE INDEX IF NOT EXISTS sandbox_sessions_acceptance_state_client_id_idx
  ON sandbox_sessions (acceptance_state, client_id);

-- NOTE: RLS posture intentionally unchanged in β.0. ADR-036
-- documents the FORCE RLS target + the β.x cutover plan + the
-- Node-side coexistence work that must land in lockstep.
