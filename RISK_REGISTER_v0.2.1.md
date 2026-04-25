# IWO3 Risk Register v0.2.1

Date: 2026-04-24
Predecessor: v0.2.0 (MegaLoop Alpha α.8 closeout).
Closeout: Pre-Beta Gap Closure Loop β.7.

This bump retires the "theoretical Telegram", "read-only admin", and "no end-to-end runtime" risks that v0.2.0 carried. New risks introduced by Pre-Beta closure are added with explicit Beta-track tags.

## Active risks

### R-021 [S1] (carried from v0.2.0) Per-WO LLM token ceiling enforced only at call-time

Unchanged. Per-call cap caps burst; audit log is forensic. Beta adds per-tenant override + faster gate.

### R-022 [S1, downgraded → S2] Telegram offset persistence is in-process

β.4 confirmed the in-process offset works for Alpha posture. ADR-027 documents the rationale; ADR-028 idempotency hardening guarantees restart-safe replays. Downgraded from S1 → S2 because the operational impact is now bounded to "extra audit rows" not "lost messages."

### R-023 [S2] (carried) Auth-code consume runs on bypass connection

Unchanged. β.4 doubles down on the cross-tenant pattern via `_handle_start_binding`; both code paths carry `lint:bypass-rls-explain`.

### R-024 [S2] (carried) Telegram bot token loss → outbound stall

Mitigation extended: β.4 telemetry logs at warning level once per failed tick instead of per failed message, reducing log noise. Beta will add `/health/channels`.

### R-025 [S2] (carried) Workflow launch from chat is deferred to Beta

Unchanged for chat. β.3 `/work_orders/{id}/dispatch` does instantiate workflow_executions from the **browser** path now, so the IWO2-equivalent operator flow is closed; only the Telegram side waits for Beta.

### R-026 [S3, retired] Tier 2 dispatch_intent path lacks transport injection seam

Resolved. β.3 `/aiden/chat` and the new `/work_orders/{id}/dispatch` route use `invoke_aiden_tier_1` directly with route-level transport mocking; `dispatch_intent` is no longer the only entry point.

### R-027 [S3, retired] CI does not run a full Telegram round-trip

Resolved. β.4 `_disabled()` test + β.5 channel-correctness regression tests cover the worker scaffolding deterministically; the live Telegram round-trip stays in F2 verification per ADR-027. The risk class moves from "CI gap" to "intentional F2 scope" — no longer a register item.

### R-028 [S3] (carried) Dev bearer auth is in production for Alpha

Unchanged. Stage A § D4 lock holds; production auth remains Beta scope (Loop 11+).

### R-029 [S2] (NEW) `system:admin` is the only RBAC gate on llm_config CRUD

ADR-025 chose `system:admin` over a new `llm_config:*` permission family to avoid bumping the vocabulary. The trade-off: any admin can change provider, model, system prompt, and credential_ref for any role. For Alpha posture (small internal multi-user) this is the right call. For Beta with external pilot tenants, finer-grained per-field permissions may be warranted.

**Mitigation:** All write paths emit audit events (`llm_config.created/updated/disabled`); operators can post-hoc review every change. Production RBAC review is Loop 11.

### R-030 [S3] (NEW) `display_name` backfill is heuristic, not authoritative

ADR-026 backfills `display_name` from `agent_role` for existing rows via a CASE expression. New tenants seeded after β.1 must provide `display_name` explicitly (column is NOT NULL). The heuristic is one-shot and won't drift, but it's not "configured" — it's the migration's best guess.

**Mitigation:** Sub-Agents Edit form lets operators rename trivially. Seed loader will be updated in Beta to carry display_name in the JSON.

### R-031 [S3] (NEW) The Streamlit "New Sub-Agent" form has no template / persona library

ADR-026 deferred persona templates. An operator creating a new Tier 2 sub-agent must paste a system prompt by hand. For Alpha posture this is fine — there are 6 canonical sub-agents and the seed already covers them.

**Mitigation:** Beta adds a persona library + "Clone from existing" flow.

## Retired (resolved in Pre-Beta β closure)

### R-old-1 [retired] Read-only admin lite

Replaced by browser CRUD per ADR-025/026. Edit + create + delete + truthful credential chip all live.

### R-old-2 [retired] Tier 1/1.5/2 helpers exist but no product flow reaches them

Replaced by ADR-021 + β.3 `/work_orders/{id}/dispatch`. Browser-side dispatch covers Tier 1 → Tier 1.5/Tier 2 → output_package end-to-end.

### R-old-3 [retired] Telegram is theoretical, not operational

Replaced by ADR-027. Polling worker active in lifespan; full Telegram lifecycle wired.

### R-old-4 [retired] Channel inbound dedup can alias cross-chat

Replaced by ADR-028. UNIQUE widened to (channel_kind, external_chat_id, external_message_id); two regression tests lock the behaviour.

## Process notes

The register is reviewed at every loop closeout. v0.3.0 expected at end of MegaLoop Beta and will retire R-021, R-024, R-028 if Beta lands per-tenant overrides + production auth + `/health/channels`.
