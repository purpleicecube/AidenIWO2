# IWO3 MegaLoop Beta — Architect Decisions v0.1.0

Date: 2026-04-25
Status: **Locked.** Architect Q1–Q15 answers received 2026-04-25; recorded verbatim below.
Predecessor: `IWO3_MEGALOOP_BETA_PRESTART_QUESTIONS_v0.1.0.md` (the question set).
Companion: `IWO3_MEGALOOP_BETA_SCOPE_PROPOSAL_v0.1.0.md`, `MEGALOOP_BETA_COVERAGE_MAP_v0.1.0.md`, `IWO3_MEGALOOP_BETA_RISK_ALIGNMENT_NOTE_v0.1.0.md`.

This memo is the **gate** between scoping and Beta-1 implementation. Beta-1 coding begins after this commit lands. Architect answers are recorded **verbatim with no reinterpretation**; impact maps are descriptive (engineering follow-through), not new policy.

## Q1 — Per-tenant LLM ceiling override schema

**Decision: A**
- Use a single column on `clients`: `llm_per_wo_ceiling`
- Reason: simplest shape, sufficient for pilot-stage operator needs, least schema overhead
- Deferred: per-role override model beyond tenant-wide ceiling

**Impact map**
- **Schema:** ALTER TABLE `clients` ADD COLUMN `llm_per_wo_ceiling INTEGER NULL`. NULL = use platform default (`DEFAULT_PER_WO_CEILING = 50_000`).
- **Runtime:** `runtime/budgets.check_or_raise_wo_budget` reads the column when populated, falls back to the constant otherwise. One extra read per dispatch; cacheable per-tenant.
- **Security:** None.
- **UX:** Aiden Settings page gets a numeric editor for the tenant ceiling; admin-only via `system:admin`.
- **Risk:** Retires R-021 partial (per-tenant tunability lands; the call-time-only timing window stays as documented residual).

## Q2 — Beta auth choice

**Decision: B**
- Use custom signed JWT with short TTL + refresh
- Reason: self-hosted, portable, not tied to Replit, no external auth dependency
- Requirement: dev bearer remains local-dev-only behind an env gate, not production canonical

**Impact map**
- **Schema:** New table `user_auth_credentials` (or extend `users`) with `password_hash`, `password_algo`, `password_updated_at`. New `auth_sessions` (or stateless via JWT only — engineering call inside Beta-1).
- **Runtime:** New `routes/auth.py` (`POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`). New `deps.current_user_context` branches on env: `IWO3_AUTH_MODE=jwt` (production) vs `IWO3_AUTH_MODE=dev_bearer` (local dev only). JWT signed with `IWO3_JWT_SIGNING_KEY` env secret.
- **Security:** Critical. Dev bearer **must** be unreachable when `IWO3_AUTH_MODE=jwt`. Sessions expire short (15 min default; 30-day refresh). HTTPS-only in production posture (operator runbook).
- **UX:** New login page in Streamlit; sidebar identity widget shows logged-in user; logout button.
- **Risk:** Retires R-028. Adds R-037 (secret rotation operational complexity).

## Q3 — Channel webhook endpoint design

**Decision: C, implemented as B primary + long-poll fallback**
- Canonical production path: `/webhook/<channel>` with signed-body verification / HMAC
- Keep long-poll worker as fallback for dev/offline environments
- Reason: production-ready shape without losing operational resilience in development

**Impact map**
- **Schema:** Per-tenant webhook secrets stored in `adapter_credentials` (existing table) with a `webhook_hmac_secret` credential_kind. Already supported.
- **Runtime:** New `routes/webhooks.py`: `POST /webhook/telegram`, `POST /webhook/slack` (latter prepared for Beta-2). HMAC verification middleware. Fallback flag `IWO3_TELEGRAM_WORKER_DISABLED=true` in production by default; webhook is canonical path.
- **Security:** Critical. HMAC verification rejects unsigned bodies; constant-time comparison. Replay-protection via timestamp window check (≤5 min).
- **UX:** Aiden Settings → Channels: shows webhook URL + HMAC secret rotation button per tenant.
- **Risk:** Adds R-039 (webhook signature gap if HMAC secret leaks). Eliminates production dependency on long-poll resilience.

## Q4 — Cost-aware provider arbitration

**Decision: A**
- Defer provider-arbitration runtime behavior beyond Beta
- Reason: keep Beta tight; do not add spend-routing logic in this phase
- Note: if a registry/data-model hook naturally appears, it may exist as inert shape only, not active arbitration

**Impact map**
- **Schema:** None in Beta-1. If a `llm_provider_costs` table appears in Beta-2 it stays inert (no arbitration logic reads from it).
- **Runtime:** None.
- **Security:** None.
- **UX:** None in Beta-1.
- **Risk:** None retired. Carries to GA.

## Q5 — RBAC granularity for config CRUD

**Decision: C**
- Split config authority into a minimal hybrid shape:
  - `llm_config:write`
  - `llm_config:delete`
- Read may remain under the existing read posture where appropriate
- Reason: enough operator/admin separation without overgrowing permission vocabulary

**Impact map**
- **Schema:** New permission keys + role mappings. Vocabulary 75 → 77 keys. Migration 0016 (Beta-1) idempotent additive.
- **Runtime:** `routes/llm.py`: PATCH/POST gates change from `system:admin` → `llm_config:write`; DELETE → `llm_config:delete`. Read stays under `client:read`.
- **Security:** Net positive — finer separation between operator (can edit) and admin (can hard-delete).
- **UX:** Sub-Agents page action buttons re-gated; viewer + reviewer remain read-only; operator can now edit but cannot delete; admin/owner retain full.
- **Risk:** Retires R-026, R-027, R-029.

## Q6 — Persona library / template profiles

**Decision: A**
- Reuse `prompt_profiles` / existing prompt-profile substrate
- Reason: avoids inventing a second persona system; keeps IWO3-native model intact
- Requirement: Aiden persona remains distinct and anchored to accepted IWO2 lineage behavior

**Impact map**
- **Schema:** None new. `prompt_profiles` from Loop 2 already supports the shape; add a convention: `prompt_profiles.scope='client'` rows keyed on `agent_role` serve as role-default personas.
- **Runtime:** `runtime/tier_1_aiden.invoke_aiden_tier_1` resolves persona via the existing prompt-profile resolver before falling back to `llm_configs.system_prompt`. Same pattern for Tier 1.5 / Tier 2.
- **Security:** None.
- **UX:** Aiden Settings + Sub-Agents pages get a "Persona templates" section; operators can pick from saved personas or apply ad hoc edits.
- **Risk:** Retires R-031 (if delivered in Beta-1; should-have status).

## Q7 — Cross-session chat context durability

**Decision: A**
- Add `chat_sessions` table keyed on `(user_id, client_id)` storing message history/state
- Reason: direct, durable, operator-facing continuity; aligns with Beta-1 must-have
- Boundary: this solves operator chat continuity, not deep agent memory across work orders

**Impact map**
- **Schema:** New table `chat_sessions` (`id`, `user_id`, `client_id`, `messages JSONB`, `context JSONB`, `created_at`, `updated_at`) with UNIQUE on `(user_id, client_id)` so each (operator, tenant) has exactly one session row. RLS forced. Migration 0016/0017.
- **Runtime:** New `routes/chat_sessions.py`: `GET /chat_sessions/me` returns the current operator's session for the tenant; `PUT /chat_sessions/me` upserts message history. Streamlit `views/chat.py` writes to + reads from this on every chat turn instead of session_state.
- **Security:** RLS-scoped per tenant + per-user filter on `user_id = ctx.user_id`. Audit emission `chat_session.updated` (locked under `BETA_PHASE_1_AUDIT_EVENTS`).
- **UX:** Browser refresh / re-login preserves chat history; "where is the output?" works after a reconnect.
- **Risk:** Retires R-032.

## Q8 — Server-side WO idempotency for chat-driven creates

**Decision: A**
- Enforce schema-level guarantee on chat-driven creates via UNIQUE on `(client_id, correlation_id)` for chat flows
- Reason: no race window; reliable
- Response behavior: duplicate attempt must be handled cleanly and explicitly, not silently create another WO

**Impact map**
- **Schema:** Partial UNIQUE index on `work_orders (client_id, correlation_id) WHERE correlation_id LIKE 'chat:%'`. Migration 0018.
- **Runtime:** `routes/work_orders.create_work_order` catches `UniqueViolationError` for the partial index → returns 409 Conflict with the existing WO id (so chat clients can deep-link to it).
- **Security:** None.
- **UX:** A duplicate Create-from-chat click still lands the operator on the original WO instead of an error. Streamlit chat replaces the in-process `iwo3_chat_promoted` guard with the server-side gate as the canonical line of defence.
- **Risk:** Retires R-033.

## Q9 — Workspace file content fetch route shape

**Decision: A**
- `GET /workspace/files/{id}/content` returns content in JSON: `{content, mime_type, encoding}`
- Text types inline
- Binary returned base64 with size cap
- Reason: simplest for Streamlit and enough for Beta-1
- Defer: more advanced streaming/download variants unless later required

**Impact map**
- **Schema:** None.
- **Runtime:** `routes/workspace.py` adds `GET /workspace/files/{id}/content`. Reads `artifacts.extracted_text`; if storage_ref is `output_package://<id>` it reaches into `output_packages.content_blocks.content_markdown`. Size cap: 4 MB base64 / 200 KB inline text. Larger → 413 Payload Too Large with a "fetch via Output Packages" hint.
- **Security:** RBAC gate `workspace:read`. RLS via tenant-scoped connection.
- **UX:** Workspace UI renders txt/md/json/csv inline; png/jpg as base64 image; pdf as download link.
- **Risk:** Retires R-035.

## Q10 — Workspace hard-delete model

**Decision: A**
- Admin-explicit hard delete via `?hard=true`
- Soft delete remains the default path
- Reason: clear operational control without forcing a GC subsystem into Beta-1

**Impact map**
- **Schema:** None new (existing `deleted_at` soft-delete column is canonical).
- **Runtime:** `DELETE /workspace/folders/{id}?hard=true` and `DELETE /workspace/files/{id}?hard=true` perform real `DELETE FROM` + cascade. RBAC gate `workspace:delete`.
- **Security:** Hard delete is operator-explicit + admin-only. Audit emits `folder.deleted` + `file.deleted` with `metadata.hardDelete: true`.
- **UX:** Confirm modal in Workspace UI before hard delete; soft-delete remains one-click.
- **Risk:** Retires R-036.

## Q11 — Per-operator scratch / pinned workspace concept

**Decision: A**
- Use a per-operator subtree model for Beta
- Reason: matches the practical IWO2 lineage concept better than introducing a separate pinning substrate now
- Defer: richer cross-tree pinning model beyond Beta if still needed

**Impact map**
- **Schema:** Optional `workspace_folders.owner_user_id NULL` (NULL = tenant-shared; non-NULL = per-operator scratch). Migration 0019.
- **Runtime:** `GET /workspace/tree` filters per-operator folders to the requesting user. New per-operator root folder seeded on first chat or first workspace visit per (operator, tenant).
- **Security:** Per-user predicate composed with the existing RLS tenant filter.
- **UX:** Workspace sidebar groups "Tenant" folders + "My scratch" folders; switching is a tab.
- **Risk:** No specific risk retired; closes a δ scope cut.

## Q12 — Beta loop-split decision

**Decision: B**
- Split Beta into:
  - `Beta-1 = Production Posture`
  - `Beta-2 = Capability Expansion`
- Reason: cleaner risk separation, better reviewability, better dependency ordering

**Impact map**
- **Process only.** Implementation order: Beta-1 first (production posture), then Beta-2 (capability expansion). No drift between the two.

## Q13 — Tool/MCP registry v1 scope ceiling

**Decision: A**
- Beta ships registry shape only:
  - schema
  - CRUD/read surface
  - visibility
- No live execution path required in Beta
- Reason: answer the architecture question without ballooning scope

**Impact map**
- **Schema:** New table `tool_definitions` and `agent_tool_acl` (or similar). Beta-2 scope (not Beta-1).
- **Runtime:** Read-only browser surface. No execution path.
- **Security:** RBAC `tool:read`/`tool:write` to be defined in Beta-2.
- **UX:** New Tools page shows registered tool definitions per tenant. Beta-2.
- **Risk:** None retired in Beta-1.

## Q14 — Slack adapter timing within loop split

**Decision: B**
- Slack belongs in `Beta-2`
- Reason: depends on Beta-1 webhook/auth posture and is capability expansion, not production posture foundation

**Impact map**
- **Process only.** Beta-2 ChannelAdapter Slack implementation reuses `dispatch_intent`, `record_inbound_message`, `queue_outbound_message`. Webhook design from Beta-1 § Q3 is the dependency Slack consumes.

## Q15 — Encrypted-at-rest credential mechanism

**Decision: B**
- Use application-side libsodium/cryptography encryption
- Encrypted bytes stored in DB
- Reason: portable, self-contained, no external KMS dependency
- Required operational add-ons:
  - operator-owned secret rotation procedure
  - explicit key-recovery runbook
  - risk/register alignment for failure modes

**Impact map**
- **Schema:** Extend `adapter_credentials` (and any other credential-bearing table) with `encrypted_value BYTEA NULL`, `encryption_algo VARCHAR`, `encrypted_at TIMESTAMP`. Existing `credential_ref:env:*` rows stay valid; encryption is layered on for non-env-resolved values. Migration 0020 (Beta-1).
- **Runtime:** New `runtime/credentials_crypto.py` wraps libsodium (`pynacl`). Master key derived from `IWO3_CRYPTO_MASTER_KEY` env. Resolver: if `credential_ref:env:NAME` → env path (current); if `credential_ref:enc:<id>` → decrypt at call time. Token credentials (Telegram bot tokens, future Slack tokens) move to encrypted storage.
- **Security:** Critical. Master key compromise = all encrypted creds at risk. Rotation runbook documents key-derivation re-run + re-encryption sweep. Lost master key = stored creds unrecoverable; runbook makes that consequence explicit before opt-in.
- **UX:** Aiden Settings → Channels: rotate-credential button issues new encrypted value transparently.
- **Risk:** Adds R-038 (key derivation single-point-of-failure). Mitigates ADR-024-deferred "encrypted-at-rest credentials". Operator-owned rotation procedure documented in runbook.

## Implication summary table

| Q | Schema change | Runtime change | Security-sensitive | UX surface | Risk delta |
|---|---|---|---|---|---|
| Q1 | ALTER `clients` | budgets resolver | — | Aiden Settings editor | R-021 partial retire |
| Q2 | new `user_auth_credentials` (likely) | new `routes/auth.py` + auth dep | **HIGH** | Login page | retires R-028; adds R-037 |
| Q3 | reuse `adapter_credentials` | new `routes/webhooks.py` + HMAC verify | **HIGH** | Channels admin UI | adds R-039 |
| Q4 | none | none | — | none | none |
| Q5 | +2 perm keys | gate-swap on llm/configs CRUD | — | Sub-Agents action gating | retires R-026/R-027/R-029 |
| Q6 | none | persona resolver chain | — | Persona templates UI | retires R-031 (should-have) |
| Q7 | new `chat_sessions` | new `routes/chat_sessions.py`, chat.py rewires | low | Chat persistence visible | retires R-032 |
| Q8 | partial UNIQUE index | 409 handling on POST /work_orders | low | duplicate-deep-link UX | retires R-033 |
| Q9 | none | new `GET .../content` | — | Workspace inline preview | retires R-035 |
| Q10 | none | DELETE ?hard=true path | — | confirm modal | retires R-036 |
| Q11 | optional `workspace_folders.owner_user_id` | tree filter + per-user seed | — | Workspace tabs | δ scope-cut closure |
| Q12 | — | — | — | — | process |
| Q13 | (Beta-2) | (Beta-2) | (Beta-2) | (Beta-2) | (Beta-2) |
| Q14 | — | — | — | — | process |
| Q15 | extend `adapter_credentials` | new `credentials_crypto.py` | **HIGH** | rotate button | adds R-038, mitigates ADR-024-deferred |

## Beta-1 must-have ↔ Q-mapping

Beta-1 ships when these gates close:

1. Production auth (Q2, Q15 partial)
2. Encrypted credentials (Q15)
3. Webhook ingress (Q3)
4. Server-side WO idempotency (Q8)
5. Cross-session chat context (Q7)
6. Workspace content fetch (Q9)
7. Workspace hard-delete (Q10)
8. `/health/channels` + `/health/llm` (no Q-direct; theme #4 in directive)
9. Per-tenant LLM ceiling (Q1)
10. RBAC granularity for config CRUD (Q5)

Beta-1 should-haves: Q11 (per-operator scratch), Q6 (persona library reuse).

Beta-1 deferred to Beta-2: Q13 (MCP registry), Q14 (Slack), and the conversational v2 + Sandbox PPTX/PDF themes from the scope proposal.

## Authorization

This memo is the formal gate. Beta-1 implementation begins immediately after this commit lands. Phases will be tagged `ε.1` through `ε.N + closeout` for α/β/γ/δ/ε continuity.

Architect-locked carry-forward rules apply:
- R-034 stays a carried operational caveat (drag-drop dep activation).
- No reopening closed Alpha or δ work unless a Beta dependency forces it.
- Operator chat continuity in Beta-1; deeper cross-WO agent memory deferred.
