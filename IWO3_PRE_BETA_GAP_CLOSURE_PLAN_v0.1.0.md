# IWO3 Pre-Beta Gap Closure — Plan v0.1.0

Date: 2026-04-24
Status: Accepted (CODEX directive 2026-04-24).
Predecessor: `MEGALOOP_ALPHA_RECORD_v0.1.0.md`.
Successor: MegaLoop Beta (separate loop).

This is a bounded loop that closes Alpha truth gaps before MegaLoop Beta opens. It is **not** Beta. It does not pull deferred Beta items forward; it lifts IWO3 to a credible, operator-usable Alpha-complete baseline.

## Phase plan

| Phase | Headline | Acceptance link |
|-------|----------|-----------------|
| β.1   | Sub-agent metadata model v1 — extend `llm_configs` (display_name, description) + migration 0012 + seed alignment + RBAC vocab if needed | Acceptance #9 |
| β.2   | LLM config CRUD parity v1 — POST/PATCH/DELETE on `/llm/configs` (admin) + truthful credential state + tests | Acceptance #6, #7, #8, #10 |
| β.3   | End-to-end runtime closure — `POST /work_orders/{id}/dispatch` runs Tier 1 → Tier 1.5/Tier 2 → output_package + `/workflows/{exec_id}/run_next_step` advances steps | Acceptance #1 |
| β.4   | Telegram runtime closure — polling worker in FastAPI lifespan; `/start` cross-tenant binding via worker; intent dispatch on tenant-scoped conn; outbox drain; last_seen_at | Acceptance #2, #3, #4 |
| β.5   | Channel correctness hardening — widen `channel_messages` idempotency scope to per-chat; tests for collision/replay | Acceptance #5 |
| β.6   | Browser CRUD UX — Sub-Agents edit/new/delete; Aiden Settings edit form; truthful credential chip | Acceptance #11 |
| β.7   | Closeout — ADRs, Risk Register v0.2.1, RECORD, REVIEW REPORT, updated F2 verification, full CI green | Acceptance #12, #13 |

## What's out (per directive § "EXPLICITLY DEFERRED TO MEGALOOP BETA")

- Slack adapter, Sandbox PPTX/PDF, MCP/tool registry, per-agent tool ACL, tool history UI, OAuth/SSO, encrypted-at-rest credentials, streaming chat, pixel-perfect IWO2 modal parity.
- Pulled-in Beta items must be flagged in the closeout record. None are anticipated.

## Architectural decisions (locked at plan time)

### β.1 schema decision
Extend `llm_configs` with two columns rather than create a parallel `sub_agent_profiles` table:

- `display_name` VARCHAR(160) NOT NULL DEFAULT (derived from `agent_role`)
- `description` TEXT NULL

Rationale: one row per (tenant, agent_role) is the existing source of truth; a second table would force every CRUD path to keep two rows in sync. The IWO2 screenshots show one record per sub-agent — same shape.

### β.2 CRUD shape
- `POST /llm/configs` — create (admin). Body: `{agent_role, display_name?, description?, provider, model, base_url?, system_prompt?, credential_ref, options?, enabled}`.
- `PATCH /llm/configs/{id}` — partial update (admin). Any of the above fields.
- `DELETE /llm/configs/{id}` — soft delete via `enabled=false`; full DELETE only on admin override flag (avoids breaking tenants that depend on the role).
- All writes RBAC-gated on `system:admin` (tenant-scoped via the existing `get_tenant_scoped_connection`). Audit events: `llm_config.created` / `llm_config.updated` / `llm_config.disabled`.
- Credential-state chip in the GET response: `{has_credential: bool, env_var_name: string}`. The raw key never leaves the FastAPI process.

### β.3 dispatch shape
Two new routes, both RBAC-gated on `work_order:update`:
- `POST /work_orders/{id}/dispatch` — read WO, run Aiden Tier 1 against `title + description`, branch:
  - work_order_brief → invoke Tier 2 with the brief, persist output_package, transition WO to `processing` then `done` if synchronous.
  - workflow_brief → instantiate workflow + step_runs (PM Tier 1.5), transition WO to `processing`, return `workflow_execution_id`.
  - clarification → return question, no DB writes.
- `POST /workflows/{execution_id}/run_next_step` — pick first `pending` step_run, execute Tier 2, mark step `completed`, return next step or workflow status.

The existing async polling for Gamma handoff stays — output_packages with `gamma_*` kinds get picked up by the existing handoff worker.

### β.4 Telegram worker
- New `workers/telegram_worker.py` lifespan task.
- Iterates `clients` rows; for each, derives the env var via `env_var_for_telegram_bot_token(client.designation)`. Skips tenants without the env var (logs at info, not warn — operators don't need to bring up Telegram for every tenant).
- Per tick (default 10s — faster than the 30s gamma poll because chats expect quick replies):
  - `fetch_inbound_batch()` from the adapter.
  - For each update, branch on bound vs unbound.
  - Bound: tenant-scoped connection, `record_inbound_message`, `dispatch_intent`, `queue_outbound_message`, `deliver_outbound`, `mark_outbound_sent`, update `last_seen_at`.
  - Unbound: bypass connection, parse_intent → if `start` then `consume_auth_code_and_bind` + reply confirm, else reply `/start` prompt.
- Disable flag: `IWO3_TELEGRAM_WORKER_DISABLED=true` (mirrors poll worker pattern).

### β.5 idempotency scope
Audit `channel_messages` UNIQUE constraint. If currently `(channel_kind, idempotency_key)` only, widen to `(channel_kind, external_chat_id, idempotency_key)` so chat A's message #42 can't collide with chat B's message #42 across the same bot. Migration 0013.

### β.6 browser UX shape
- Sub-Agents page: each row gets an "Edit" expander with a form (provider dropdown, model field, base URL field, system prompt textarea, enabled toggle, display_name input, description textarea, save button). "New Sub-Agent" button at top opens a fresh form. "Disable" button per row instead of hard delete.
- Aiden Settings page: existing "Aiden Tier 1 resolved config" section gets an Edit toggle that swaps the read-only display for the same form.
- Credential state chip: green "✅ ENV set" if the env var resolves, red "⛔ ENV missing" otherwise.

## Known dependencies and risks

- Migrations 0012 + 0013 are additive and idempotent. No data loss path.
- The existing role-permission cardinality assertions in `tests/integration/role-permission-resolution.test.ts` will need a bump if β.1 introduces `llm_config:*` permissions. Decision: piggyback on `system:admin` for now (already enforced in the LLM routes). No new RBAC keys needed for β.2.
- The Telegram worker iterating all tenants is O(N tenants). For Alpha posture with ≤5 tenants this is fine; documenting the linear scan in the worker for future readers.

## Closeout artifacts (β.7)

Required by directive:

- `IWO3_PRE_BETA_GAP_CLOSURE_RECORD_v0.1.0.md`
- Alpha review packet addendum (`IWO3_ALPHA_REVIEW_ADDENDUM_v0.2.0.md`)
- Updated `RISK_REGISTER_v0.2.1.md`
- ADRs as needed:
  - ADR-025 — LLM config CRUD model
  - ADR-026 — Sub-agent metadata model
  - ADR-027 — Telegram runtime worker
  - ADR-028 — Channel idempotency scope correction
- Optional: `IWO3_PRE_BETA_GAP_CLOSURE_CODEX_REVIEW_REPORT_v0.1.0.md`

## Definition of done (mirroring directive)

- Core runtime path is product-reachable end-to-end (Submit → dispatch → Tier 2 → output_package → handoff).
- Telegram is truly operational (worker running, inbound persisted, outbox draining, last_seen_at updated).
- Aiden / Sub-Agent management surface supports real edits.
- Sub-agent metadata model v1 landed and used by UI.
- Channel idempotency scope corrected.
- Documentation reflects the new truth.
- All CI green; no new regressions.
