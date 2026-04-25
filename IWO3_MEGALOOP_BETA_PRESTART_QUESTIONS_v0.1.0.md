# IWO3 MegaLoop Beta — Prestart Questions v0.1.0

Date: 2026-04-25
Status: Draft for CODEX review.
Companion to: `IWO3_MEGALOOP_BETA_SCOPE_PROPOSAL_v0.1.0.md`.

This is the formal Stage 0 question set for MegaLoop Beta. Coding does not start until each question carries a locked architect answer.

Question categories:
- **Carried** — questions surfaced by prior loops (Alpha closeout, β.7, γ, δ) without a final architect decision.
- **New (δ)** — questions surfaced by Loop δ closeout that didn't exist at α.8.
- **New (Beta)** — questions specific to Beta scoping that this proposal raises.

## Carried (8) — from prior closeouts

### Q1. Per-tenant LLM ceiling override schema

Context: ADR-021 made the per-WO ceiling a constant (50K). Beta must-have allows per-tenant override.

Options:
- (a) Single column on `clients` (`llm_per_wo_ceiling`).
- (b) Separate `llm_quotas` table keyed on `(client_id, agent_role)` for per-role overrides.
- (c) Operator-policy registry (broadest, most schema).

**Default:** (a) — simplest, satisfies the operator-pilot use case. (b) deferred to GA if per-role tuning becomes needed.

### Q2. Beta auth choice

Context: Stage A § D4 deferred production auth. Beta must-have closes R-028.

Options:
- (a) Replit OAuth (matches IWO2 lineage).
- (b) Custom signed JWT with short TTL + refresh.
- (c) External provider (Auth0 / WorkOS / Clerk).

**Default:** (b) — keeps IWO3 self-hosted; (a) ties IWO3 to Replit which is a posture choice; (c) adds an external dependency.

### Q3. Channel webhook endpoint design

Context: Alpha shipped long-poll (Telegram). Beta must support Slack which is webhook-native.

Options:
- (a) Path-based per-tenant secret: `/webhook/<channel>/<tenant_secret>`.
- (b) One endpoint with `update_id` cross-reference + signed body verification: `/webhook/<channel>` with HMAC.
- (c) Both — long-poll stays as fallback, webhook as primary in production.

**Default:** (b) + (c) — webhook with HMAC for production; long-poll worker stays for offline / dev. Per-tenant secret lives in `adapter_credentials`.

### Q4. Cost-aware provider arbitration

Context: ADR-021 ruled this Beta-or-later. Beta should consider whether the **registry shape** lands now even if execution doesn't.

Options:
- (a) No-op in Beta — defer everything to Loop 12.
- (b) Land a `llm_provider_costs` table + browser surface read-only; runtime arbitration ships post-Beta.
- (c) Land registry + a static priority list (cheapest-first per role); no dynamic arbitration.

**Default:** (a) — keep Beta tight. (b) is reasonable if the architect wants visibility into spend modeling.

### Q5. RBAC granularity for config CRUD

Context: Beta must-have. ADR-025 noted the `system:admin`-only gate trade-off.

Options:
- (a) Add `llm_config:create / read / update / delete` keys (4 new permissions, ~16 new role rows).
- (b) Keep `system:admin` and document the carry-forward in an ADR.
- (c) Hybrid: split write into `llm_config:write` + `llm_config:delete`; read stays under `client:read`.

**Default:** (c) — minimum vocabulary growth that still gives operator-vs-admin separation.

### Q6. Persona library / template profiles

Context: ADR-026 deferred. Beta should-have ships if scope allows.

Options:
- (a) Reuse Loop 2's `prompt_profiles` for sub-agent default personas; add a per-role lookup.
- (b) New `persona_templates` table dedicated to role personas.
- (c) Operator-only (manual edit per `llm_config.system_prompt`); no template machinery.

**Default:** (a) — reuse the existing prompt-profile substrate.

### Q7. Cross-session chat context durability

Context: γ.1/2 made chat context session-scoped. R-032 carries the gap.

Options:
- (a) New table `chat_sessions` keyed on `(user_id, client_id)` storing message history JSON.
- (b) Per-message rows in `channel_messages` (extending the existing inbound/outbound table).
- (c) DigiFlow/external memory store (e.g. SQLite per-tenant, Redis).

**Default:** (a) — clean schema, mirrors IWO2's `aiden_chat_messages` pattern.

### Q8. Server-side WO idempotency for chat-driven creates

Context: R-033 from γ. Beta must-have.

Options:
- (a) UNIQUE on `(client_id, correlation_id)` for `chat:*` correlations; 409 on dup.
- (b) Application-side check before INSERT.
- (c) Idempotency-Key header pattern (Stripe-style) on `POST /work_orders`.

**Default:** (a) — schema-level guarantee, no race window.

## New (3) — from Loop δ

### Q9. Workspace file content fetch route shape

Context: R-035 from δ. Beta must-have.

Options:
- (a) `GET /workspace/files/{id}/content` returns full text in JSON (`{content, mime_type}`); base64 for binary.
- (b) Signed URL pattern: returns `{url, expires_at}`; UI fetches separately.
- (c) Streaming endpoint with `Content-Type` honored.

**Default:** (a) — simplest, works for txt/md/json/csv inline; binary uses base64 with a size cap.

### Q10. Workspace hard-delete model

Context: R-036 from δ. Beta must-have.

Options:
- (a) Admin-explicit per-row hard delete with `?hard=true` (mirrors α.6 LLM config DELETE pattern).
- (b) Scheduled GC sweep on `deleted_at > 30d`.
- (c) Both — operator can hard-delete now; sweep cleans the rest.

**Default:** (a) for Beta; (c) for GA. Beta operator pilots are small enough that a sweep isn't critical.

### Q11. Per-operator scratch / pinned folders

Context: from δ scope-cut and architect note "artifact integration as center of gravity". Beta should-have.

Options:
- (a) Per-operator subtree: each operator gets a `~/<user_id>/` folder under tenant root, scoped by `created_by_user_id` filter.
- (b) Global `pinned_artifacts` table — orthogonal to folder tree.
- (c) Both — per-operator subtree + cross-tree pin.

**Default:** (a) for Beta; (c) for GA. Pinning is nice-to-have; per-operator scratch is the IWO2 lineage concept.

## New (4) — Beta scoping itself

### Q12. Beta loop-split decision

The proposal recommends splitting Beta into **Beta-1 (Production Posture)** + **Beta-2 (Capability Expansion)** for risk-profile and reviewability reasons.

Options:
- (a) Single MegaLoop Beta with 14 must-haves + closeout.
- (b) Beta-1 + Beta-2 as recommended (Beta-1 first; Beta-2 depends on Beta-1's webhook + auth foundations).
- (c) Three loops: Production Posture / Channels-and-Adapters / Aiden+Tools (further split).

**Default:** (b) — matches β/γ/δ split rhythm.

### Q13. Tool/MCP registry v1 scope ceiling

Context: theme #6 in directive. Beta must-have on registry shape; theme calls for "direction".

Options:
- (a) Schema + CRUD + browser surface; **no execution path** in Beta.
- (b) Schema + CRUD + browser surface + read-only "test invoke" against a single MCP server (proof-of-concept).
- (c) Full registry + per-agent ACL + execution path on a small subset of tool types.

**Default:** (a) — registry shape only; execution is post-Beta. Per the directive's "do not assume all themes belong in Beta."

### Q14. Slack adapter timing within the loop split

If we go (b) on Q12: does Slack live in Beta-1 or Beta-2?

Options:
- (a) Slack in Beta-1 alongside the channel webhook design (forces the design to be Slack-real, not theoretical).
- (b) Slack in Beta-2 after Beta-1's webhook foundation is closed.

**Default:** (b) — keeps Beta-1 tight on production posture; Slack is a capability-expansion item.

### Q15. Encrypted-at-rest credential mechanism

Context: Beta must-have. ADR-024 deferred this.

Options:
- (a) `pgcrypto` symmetric encryption inside Postgres; key derivation from a runtime secret.
- (b) Application-side libsodium/cryptography library; encrypted bytes stored in `credential_value` column.
- (c) External KMS (AWS KMS / GCP KMS) — operator owns the encryption key; IWO3 only decrypts via API call.

**Default:** (b) — self-contained, no external dependency, works on Replit / Railway / bare-metal alike.

## Optional carried items not yet on the question list

These exist in prior records but aren't blocking — flag if architect wants any pulled forward into the question matrix:

- `R-022` Telegram offset durable persistence (currently bounded; could become `channel_identities.last_offset`).
- `R-023` auth-code consume on bypass connection (architectural by design; documented).
- `R-026` workflow launch from chat (could be folded into Q7 Beta cross-session context).
- ADR-024's deferred list outside Beta scope (Slack is now must-have; Sandbox is must-have; the rest stay deferred).

## Authorization protocol

Per the loop discipline established in α / β / δ:

1. CODEX answers Q1–Q15 with locked decisions.
2. Implementation team writes a decision memo (`IWO3_MEGALOOP_BETA_DECISIONS_v0.1.0.md`) recording the answers verbatim.
3. Beta (single loop or Beta-1) coding starts.
4. The 4 required scoping artifacts (`SCOPE_PROPOSAL`, `PRESTART_QUESTIONS`, `COVERAGE_MAP`, `RISK_ALIGNMENT_NOTE`) plus the decision memo become the gating record set.

This protocol mirrors Stage A's IWO3_ALPHA_PRESTART_DECISIONS_v0.1.0.md pattern.
