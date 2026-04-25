# ADR-029 — Beta-1 production posture (auth + webhooks + idempotency + ceilings + RBAC)

Date: 2026-04-25
Status: Accepted (MegaLoop Beta-1 ε.10 closeout).
Predecessors: ADR-024 (Alpha release definition), ADR-022 (channel layer), ADR-023 (Telegram adapter), ADR-025 (LLM config CRUD), ADR-021 (LLM runtime).
Companions: `IWO3_MEGALOOP_BETA_DECISIONS_v0.1.0.md` (architect Q1–Q15 lock), `IWO3_MEGALOOP_BETA_1_RECORD_v0.1.0.md`.

## Context

Alpha proved the runtime; Pre-Beta closed operator-trust gaps. Beta-1 must prove IWO3 is safe to hand to a non-development pilot tenant. The architect locked five production-posture decisions that drive this loop: per-tenant LLM ceilings (Q1), production auth (Q2), webhook ingress (Q3), RBAC granularity for config CRUD (Q5), server-side WO idempotency for chat creates (Q8). This ADR documents how those locks landed, the trade-offs taken, and the carry-forwards.

## Decisions

### 1. Production auth — stdlib HMAC-SHA256 JWT

`auth/jwt_tokens.py` implements HS256 with stdlib (`hmac`, `hashlib`, `base64`, `json`, `secrets`). No third-party library dependency. Public API (`encode`, `decode`, `TokenError`) is shaped to match `pyjwt` so an operator can swap implementations later without changing call sites.

**Why stdlib instead of pyjwt:** PyPI was unreachable in the development sandbox. Stdlib HS256 is industry-standard, ~150 LOC including tests, and the pyjwt swap is mechanical when the operator runs `uv add pyjwt`.

**Threat-model posture:**
- Fixed header rejects `alg=none` confusion attacks.
- Constant-time signature compare via `hmac.compare_digest`.
- 15-min access TTL + 30-day refresh TTL defaults.
- Replay protection via `exp` only — Beta-1 has no JTI revocation list. Sessions revoke at TTL boundary; mass logout = key rotation.
- Signing key from `IWO3_JWT_SIGNING_KEY` env (≥32 bytes required at runtime).

**Auth-mode env gate:** `IWO3_AUTH_MODE=jwt` makes the bearer header canonical; `IWO3_AUTH_MODE=dev_bearer` (default) keeps the legacy `X-IWO3-User` + `X-IWO3-Client` pair for local development. The bearer header takes precedence in either mode, so a JWT works even when `dev_bearer` is the configured default.

**Password storage:** PBKDF2-HMAC-SHA256 with 600,000 iterations (OWASP 2023). 16-byte salt. Format: `pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>`.

### 2. Webhook ingress — HMAC primary, long-poll fallback

`POST /webhook/telegram` accepts two signature paths:

- **Generic HMAC** (`X-IWO3-Webhook-Signature: sha256=<hex>` + optional `X-IWO3-Webhook-Timestamp` for replay protection within 5 min). Per-tenant secret in `IWO3_WEBHOOK_HMAC_<TENANT>` env var.
- **Telegram native** (`X-Telegram-Bot-Api-Secret-Token` literal-string compare; same secret).

Signature verification iterates active tenants and checks each tenant's secret against the body — O(N tenants), acceptable at pilot scale (≤5 tenants). Constant-time compare via `hmac.compare_digest`. `webhook.signature_invalid` audit emitted on rejection; `webhook.received` on success.

The long-poll worker from α.6 stays running, gated by `IWO3_TELEGRAM_WORKER_DISABLED`. Production runs with the worker disabled and the webhook canonical; dev / offline runs with the worker enabled.

**Why both:** the architect chose `C` ("both") — production-ready shape without losing operational resilience in dev. Slack (Beta-2) inherits the same shape — the `/webhook/slack` endpoint exists at Beta-1 closeout but returns 503 until the adapter ships.

### 3. Server-side WO idempotency for chat creates

Migration 0016 introduced a partial UNIQUE index `work_orders (client_id, correlation_id) WHERE correlation_id LIKE 'chat:%'`. Non-chat correlations (`telegram:`, manual operator, `dispatch:`) keep their pre-Beta freedom to repeat — the index doesn't touch them.

`POST /work_orders` for `chat:*` correlations runs a pre-flight SELECT before INSERT. A duplicate returns 409 + the existing WO id + title so chat clients can deep-link to the original instead of erroring. The pre-flight pattern (rather than catching `UniqueViolation` post-INSERT) avoids leaving asyncpg's tenant-scoped tx in a failed state — the partial UNIQUE remains the canonical race-safe gate at the DB layer.

### 4. Per-tenant LLM per-WO ceiling

`clients.llm_per_wo_ceiling` (INTEGER NULL). NULL = use platform default (`DEFAULT_PER_WO_CEILING = 50_000`). `runtime/budgets.resolve_per_wo_ceiling` reads the column and sanity-clamps to `[1_000, 1_000_000]` so a misconfigured tenant column doesn't unlock unlimited spend or zero-out usage.

The check is a single SELECT per dispatch — fine at pilot throughput. A per-tenant cache layer is a Beta-2 follow-up if it bites.

### 5. RBAC granularity for config CRUD — split write/delete

Two new permission keys: `llm_config:write` (owner / admin / operator) and `llm_config:delete` (owner / admin only). Read continues to flow through `client:read`. This gives operators meaningful edit access without conflating it with hard-delete authority.

Total vocabulary: 75 → 77 keys. Total role-permission rows: 235 → 240. Per-role bumps in lockstep with the cardinality assertions.

## Consequences

- A pilot tenant can be onboarded with production-grade auth (JWT), webhook ingress (HMAC), and per-tenant token budgets. The dev-bearer path is now opt-in via env gate.
- Chat-driven WO creates are server-side race-safe. The duplicate-button-click failure mode that γ.1 fixed at the client now has a DB-layer floor.
- Operators can edit LLM configs without holding `system:admin` — the permission they need to delete a config still requires admin escalation.
- The webhook design is locked at Beta-1 closeout; Slack reuses the shape in Beta-2 with no architectural surprise.

## Carry-forwards (acknowledged)

- **Q15 encrypted-at-rest credentials** — `pynacl` install was blocked in the offline sandbox. Credential storage continues to use `credential_ref:env:NAME` (env secrets, never DB-stored). Beta-1.5 lands the encryption layer once `uv add pynacl` runs on a networked host. Same operational pattern as **R-034** (drag-drop dep). Tracked as **R-045** in the v0.3.0-partial register.
- **Q7 / Q11 / Q1 / Q6 UI surfaces** — backend + RBAC + schema in place; Streamlit-side wire-up (chat persistence, per-operator scratch, ceiling editor, persona-template picker) lands in Beta-1.5 alongside the encryption layer.
- **R-034 drag-drop dep activation** — unchanged; carried operational caveat per architect 2026-04-25.

## Out-of-scope (deferred to Beta-2 or GA)

- Cost-aware provider arbitration runtime (Q4 deferred).
- Tool/MCP registry execution (Q13 — shape only in Beta-2).
- Slack adapter implementation (Q14 — Beta-2).
- Streaming LLM responses (GA).
- Cross-channel identity merging (GA).
- Multi-region / HA / DR (GA).

## Threat model — what this ADR does not address

- An attacker who steals `IWO3_JWT_SIGNING_KEY` can forge tokens. Mitigation: env-only storage + rotation runbook in Beta-1.5.
- An attacker who steals `IWO3_WEBHOOK_HMAC_<TENANT>` can forge inbound webhooks. Mitigation: 5-min replay window, audit trail of `webhook.signature_invalid`, per-tenant rotation.
- The login route's email lookup runs on a bypass connection (necessary architectural exception — operator hasn't picked a tenant yet). Mitigation: uniform 401 response, no email-existence oracle, audit on every failed attempt.

These trade-offs are documented in **R-037**, **R-039**, **R-044** in the v0.3.0-partial register.
