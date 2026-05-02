-- Beta-2 phase 0.1 — operator-driven output requests.
-- Adds the `requested_outputs` jsonb column to `work_orders` so the Submit
-- Order form can carry an optional `{output_kind, template_profile_id}`
-- intent through to the auto-dispatch worker (Phase 0.2). Tier 1.5 PM
-- consults this column when instantiating a workflow; absence falls back
-- to Aiden Tier 1 LLM inference (Q3=B locked: optional with "let Aiden
-- decide" default).
--
-- Storage shape rationale (Q6=A locked): jsonb is narrow for v0
-- (single artifact intent), promotable to a first-class
-- work_order_output_requests table in Phase 1 if multi-output planning
-- lands. Keep the migration narrow.

ALTER TABLE "work_orders"
  ADD COLUMN IF NOT EXISTS "requested_outputs" jsonb;

COMMENT ON COLUMN "work_orders"."requested_outputs" IS
  'Beta-2 phase 0.1 (Q6=A): optional operator-supplied artifact intent. Shape: {"output_kind": <template_profiles.output_kind>, "template_profile_id": <uuid>}. NULL = Aiden Tier 1 infers from intake text.';
