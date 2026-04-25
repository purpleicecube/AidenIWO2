# ADR-027 — Telegram runtime worker

Date: 2026-04-24
Status: Accepted (Pre-Beta β.4)
Predecessors: ADR-022 (channel layer), ADR-023 (Telegram adapter), ADR-021 (LLM runtime).
Companions: `IWO3_PRE_BETA_GAP_CLOSURE_PLAN_v0.1.0.md` § β.4.

## Context

α.6 shipped the Telegram **adapter** — `TelegramAdapter` with `fetch_inbound_batch()` + `deliver_outbound()`, plus `dispatch_intent()` that maps parsed intents to RLS-bound runtime actions. What it did **not** ship was the runtime loop that calls those helpers. Telegram was theoretical: the adapter existed, the routes existed, the audit events were locked, but no inbound message ever reached `dispatch_intent` because nobody was polling.

Pre-Beta acceptance criterion #2 ("inbound polling/processing loop or equivalent runtime path") and #4 ("outbound replies are actually sent") require the loop.

## Decision

### 1. Lifespan task in `workers/telegram_worker.py`

A second background task in `main.lifespan`, parallel to the existing Gamma `poll_worker_loop`. Both share the same DB pool and the same shutdown semantics.

```python
worker_task   = asyncio.create_task(poll_worker_loop(get_db_pool()))
telegram_task = asyncio.create_task(telegram_worker_loop(get_db_pool()))
```

### 2. Tenant scan via env-var presence

Each tick lists `clients` rows in `active` status, derives the env var via `env_var_for_telegram_bot_token(client.designation)`, and includes the tenant only if the env var resolves. Tenants without a configured bot are silently skipped (no warning per tick). Adding a tenant is two operator actions — set the env var + restart FastAPI — no DB seed.

### 3. Three-branch update handler

Per parsed intent:

- **`/start <code>`** → bypass connection → `consume_auth_code_and_bind()` (cross-tenant) → reply confirmation.
- **bound chat** → tenant-scoped tx → `record_inbound_message` → `dispatch_intent` → `queue_outbound_message` → update `last_seen_at` → `mark_inbound_processed`. Then outside the tx: `deliver_outbound` → `mark_outbound_sent`.
- **unbound chat (anything else)** → reply with `/start <code>` prompt; no DB writes (the bot needs no state for unbound chats).

### 4. last_seen_at on every bound inbound

Updated in the same tx as `mark_inbound_processed` so the operator console's bound-identity list stays useful for "is this chat alive?" queries.

### 5. Outbox drain runs OUTSIDE the inbound tx

A slow Telegram POST cannot hold a tenant-scoped lock. Failure path → `mark_outbound_attempt_failed` leaves the row in `pending` for the next tick to retry. Success path → `mark_outbound_sent` with the Telegram-assigned message_id.

### 6. Cancellation + disable

`IWO3_TELEGRAM_WORKER_DISABLED=true` short-circuits the loop. `conftest.py` sets it for pytest by default — every `TestClient(app)` would otherwise spin up a real polling loop and try to call Telegram with whatever stale env happens to be set. Production toggle off via the same flag.

### 7. Tick cadence — 10 seconds

Faster than the 30s gamma poll because chats expect quick replies; floor at 3s to avoid hot-looping. Long-poll is set to 1s in worker mode (the worker tick gates cadence; the long poll is just to absorb any in-flight updates). Operators can override via `IWO3_TELEGRAM_WORKER_TICK_SECONDS`.

### 8. Offset persistence — in-process only (Alpha-grade)

`_tenant_offsets` is a module-level dict that resets on worker restart. A restart re-replays up to ~24h of historical updates from Telegram, which is bounded and idempotent (the inbound UNIQUE per ADR-028 prevents duplicate persistence). Promoting offsets into per-tenant DB storage is Beta — see Risk R-022.

## Consequences

- Telegram is a real operational surface. Operators can issue an auth code, bind a chat with `/start CODE`, and use `/status`, `create wo:`, `/approve`, `/reopen`, `/unblock` — all of which hit the real runtime + audit log.
- The pattern generalises: a Slack worker or email worker would be a near-drop-in copy with a different adapter constructor.
- Restarts of the FastAPI process are inexpensive — at-least-once delivery + idempotent inbound mean no operator-visible state is lost.

## Out-of-scope (deferred)

- Webhook ingress (Beta — paired with public-facing FastAPI endpoint).
- Per-tenant offset persistence.
- Inline keyboards / callback queries.
- Voice / file uploads from Telegram (Beta).
- Cross-channel identity merging (Beta).
