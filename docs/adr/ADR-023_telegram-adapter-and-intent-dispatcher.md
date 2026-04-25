# ADR-023 — Telegram adapter + intent dispatcher

Date: 2026-04-24
Status: Accepted (MegaLoop Alpha α.6)
Predecessors: ADR-021 (LLM runtime + Tier 1/1.5/2), ADR-022 (channel layer).
Companions: `IWO3_ALPHA_PRESTART_DECISIONS_v0.1.0.md` (Stage A § B1, B2, B4, B7), Stage A audit-event lock (`ALPHA_PHASE_A5_AUDIT_EVENTS`).

## Context

Telegram is the mandatory chat surface for Alpha (Stage A § B1). Operators expect to be able to:

- bring up a per-tenant bot without merging code (Stage A § B4: per-tenant tokens via `credential_ref:env:TELEGRAM_BOT_TOKEN_<TENANT>`),
- bind a chat to a specific operator with `/start <code>`,
- check WO status, create a WO from a one-line natural-language brief, and approve / reopen / unblock WOs without leaving the chat (Stage A § B2 mandatory action set).

The hard requirement is that all of those flows go through the same Aiden Tier 1 + RBAC + RLS gates that the browser uses, with no shortcut paths.

## Decision

### 1. Per-tenant bot tokens via env name derivation

`channel/telegram.env_var_for_telegram_bot_token("IWO | Klear.ai")` → `"TELEGRAM_BOT_TOKEN_KLEAR_AI"`. The adapter resolves the token at every `getUpdates` / `sendMessage` call:

```python
TelegramAdapter(client_id=..., env_var="TELEGRAM_BOT_TOKEN_KLEAR_AI", env=os.environ)
```

The polling worker iterates over tenants and constructs one adapter per `(client_id, env_var)` pair. Missing env var → `TelegramApiError("credential_missing")` and the worker logs + skips that tenant for the tick. No code changes when adding a tenant; only env config.

### 2. Long-polling, not webhooks (Alpha)

`fetch_inbound_batch()` calls `getUpdates?timeout=25&offset=...`. The adapter persists `next_offset` in memory for now; promoting it to `channel_identities`-scoped storage is a Beta concern (the polling worker re-creates adapters every tick, so a process restart re-reads the last 24 hours of updates worst case). Even non-text updates (callback queries, photos) advance the offset so we don't loop on them.

Webhooks are deferred because (a) the dev environment is not internet-exposed and (b) the local polling loop is sufficient for the small internal multi-user usage Alpha targets (Stage A § F1).

### 3. Outbound via httpx with idempotency

`deliver_outbound(external_chat_id, payload)` POSTs to `sendMessage` and returns the Telegram-assigned `message_id`. The caller writes that into `channel_messages.external_message_id`, completing the pending → sent transition. Network errors raise `TelegramApiError("network_error")` and the outbox stays in `pending` for the next tick. Hard 4xx (api_error / http_error) → `mark_outbound_attempt_failed` so the operator can see the failure in the audit log.

### 4. Intent parser — pure, regex-based

Stage A § B2 mandatory set:

```
/start CODE                    → start  (cross-tenant; bind via auth code)
/status WO_ID                  → status
/create_wo TEXT                → create_wo (slash form)
create wo: TEXT                → create_wo (natural-language form)
/approve WO_ID                 → approve
/reopen WO_ID                  → reopen
/unblock WO_ID                 → unblock
```

`parse_intent` is pure (no DB, no env). Tests cover each pattern + the unknown-fallback that surfaces a usage hint to the user. Patterns are case-insensitive on the slash command and DOTALL on the create-wo body so paste-from-richtext works.

### 5. Intent dispatcher — RLS-bound action

`dispatch_intent(conn, intent, identity)` is the only function that touches a DB row. It is always invoked on a tenant-scoped connection (the worker sets `app.current_client_id` from `identity.client_id` before each call). The actions:

- **status**: `SELECT … FROM work_orders WHERE id = $1 AND client_id = $2` with friendly fallbacks for invalid UUID + not-found.
- **create_wo**: `invoke_aiden_tier_1` → branch on `decision_kind`:
  - `work_order_brief` → `INSERT INTO work_orders` with `correlation_id = "telegram:<chat_id>"`. Reply with `assigned_role` + `priority`.
  - `workflow_brief` → also create a WO so polling `/status` works; multi-step PM Tier 1.5 instantiation is operator-driven from the browser per Stage A § B2 ("workflow launch deferred to Beta").
  - `clarification` → reply with the question; no DB writes.
  - `LlmBudgetExceeded` / `AidenInvocationError` → friendly reply, no WO.
- **approve / unblock**: `transition_work_order(to='completed' | 'processing', reason='telegram:approve from chat <id>')`.
- **reopen**: `transition_work_order(to='pending', reason='telegram:reopen from chat <id>')`.

Errors from `transition_work_order` (`PermissionDenied`, `IllegalTransition`, `RowNotFound`) are mapped to friendly Telegram replies that name the missing permission, the offending state, or the WO id. The audit row for each transition is written by `wo_wf.transitions`, not by the dispatcher — the dispatcher writes only the channel-message lifecycle rows.

### 6. RBAC enforcement

The bound user's role drives `transition_work_order`'s permission check via `client_memberships`. The dispatcher does not duplicate the gate; it just maps the typed exception into a chat reply. This means a `viewer` role can `/status` but cannot `/approve`, and the reply text says exactly which permission is missing.

## Consequences

- An operator brings up a tenant's Telegram surface in two steps: set the env var + issue the auth code. No code change, no DB seed.
- The same intent-parser tests run in CI without a real bot token.
- The dispatcher is channel-agnostic. Slack will reuse it on `dispatch_intent(conn, intent, identity)` once the Slack adapter writes to `channel_messages` and the Slack auth-code flow is approved.
- The Tier 1 LLM call is the most expensive part of `create_wo`. The per-WO ceiling protects against a runaway loop; still, an operator who pastes a 4 000-character prompt is one chat message away from spending 20K tokens. We accept this for Alpha and revisit cost-aware throttling in Loop 11+.

## Out-of-scope (deferred)

- Workflow launch from chat (Beta).
- Inline keyboards / callback query handling (Beta — Alpha is text-only).
- Voice / file uploads from Telegram (Beta).
- Webhook delivery (Beta, paired with a public-facing FastAPI endpoint).
- Cross-tenant chat visibility for super-admins (Loop 11+).
