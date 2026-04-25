# ADR-022 — Channel layer (identities, auth codes, messages, RLS)

Date: 2026-04-24
Status: Accepted (MegaLoop Alpha α.5)
Predecessors: ADR-014 (RBAC), ADR-015 (RLS enforcement + tenant context), ADR-018 (FastAPI runtime).
Companions: `IWO3_ALPHA_PRESTART_DECISIONS_v0.1.0.md` (Stage A § B1, B2, B5, B7), Stage A audit-event lock (`ALPHA_PHASE_A5_AUDIT_EVENTS`).

## Context

IWO2 grew an organic email/Slack outbox with the WO write-side, and inbound chat was a side-band that talked to a separate process. That split made tenant-attribution fragile (which tenant does this DM belong to?) and made testing impossible because the inbound and outbound writers had different RBAC + RLS posture. MegaLoop Alpha needs Telegram (mandatory per Stage A § B1) and the architecture has to leave room for Slack / email / SMS without a re-shape, so we settled the data shape and the principal-binding flow before writing the Telegram adapter (α.6).

## Decision

### 1. Three tables, one outbox-by-direction

```
channel_identities    (client_id, channel_kind, external_id) UNIQUE
channel_auth_codes    code UNIQUE (cross-tenant lookup before bind)
channel_messages      direction = inbound | outbound
                      status (inbound)  : received | processed | failed
                      status (outbound) : pending | sent | failed
```

`channel_messages` is the outbox. There is no separate `outbox` table; pending outbound rows ARE the queue. The Telegram adapter (and future Slack/email) drains them via `mark_outbound_sent` after a successful provider call. Idempotency lives on `(channel_kind, idempotency_key)` UNIQUE — the queueing helper `queue_outbound_message` short-circuits on conflict and returns the existing row.

### 2. /start auth-code binding flow (Stage A § B7)

The bot doesn't know the tenant until the chat sends `/start <code>`. So:

1. **Operator issues the code.** Browser → `POST /channel/auth_codes` (RBAC: `channel_auth_code:issue`). Insert with `status='pending'`, 15-minute TTL by default. Audit `channel_auth_code.issued`.
2. **User DMs the bot with `/start <code>`.** The Telegram adapter looks the code up by **PK only** (cross-tenant). `consume_auth_code_and_bind`:
   - Verifies `status='pending'` and `expires_at > now()`. `pending` is the security boundary — nobody else can race-consume because the UPDATE is gated on `status='pending'`.
   - Verifies `channel_kind` matches.
   - Marks `status='consumed'` + records `consumed_external_id` (the chat_id).
   - Upserts a `channel_identities` row with `status='active'` (revives a prior revoked binding via `ON CONFLICT (client_id, channel_kind, external_id) DO UPDATE`).
3. **Subsequent inbound traffic.** `find_active_identity(channel_kind, external_id)` is the per-message principal lookup. It returns `None` for unbound chats; the adapter replies "send `/start <code>`" and writes nothing.

The two cross-tenant write paths (the expiry sweep and the bind itself) carry explicit `lint:bypass-rls-explain` annotations. The lint plugin allow-listed those paths. There are no other cross-tenant paths in the channel module.

### 3. RLS posture

All three tables enable + force RLS with the same `app.current_client_id` GUC pattern from ADR-015. The bypass connection is reserved for the auth-code consume path (which has no tenant context until the consume succeeds). Inbound + outbound write paths run on the tenant-scoped connection identified by `find_active_identity`'s lookup. Outbox reads from the polling worker also run scoped — the worker iterates per-tenant and sets the GUC before each batch.

### 4. Audit vocabulary (locked)

`ALPHA_PHASE_A5_AUDIT_EVENTS` is the canonical list:

```
channel_auth_code.issued
channel_identity.bound
channel_identity.revoked
channel_message.received
channel_message.processed
channel_message.failed
channel_message.send_queued
channel_message.sent
```

The `failed` event covers both inbound parse-failures and outbound delivery-failures; the discriminator lives in `target_type` + metadata.

### 5. RBAC (single-colon convention)

```
channel_auth_code:issue   → owner / admin / operator
channel_identity:read     → owner / admin / operator / reviewer / agent_system
channel_identity:revoke   → owner / admin
```

Migration `0011_alpha_phase_6_channel_permissions.sql` adds these idempotently. Total permissions vocabulary: 69 → 72. Total `role_permissions` rows: 213 → 223. Cardinality assertions in the existing test suites are bumped in lock-step.

## Consequences

- A new channel kind (slack/email/sms) is a single ChannelAdapter implementation away. The data shape doesn't change. The polling worker registry pattern from α.1 (`adapter/poll_registry.py`) lets us register channel pollers the same way as Gamma's poll handler.
- Cross-tenant auth-code lookup is intentional and fenced. The bypass-rls-explain annotations are PR-required so future readers see the rationale.
- An attacker who guesses a 12-character base32 code has ~5 × 10⁻¹⁸ odds per attempt; the global UNIQUE on `code` plus the `pending` status gate makes brute-force impractical inside the 15-minute TTL. Rate-limiting on `/start` is deferred to the Telegram-bot side (Telegram itself rate-limits message volume per chat).
- The expiry sweep runs lazily on consume rather than via a scheduled job; expired codes are visible to operators in the UI but don't accumulate junk audit rows.

## Out-of-scope (deferred)

- Webhook-based inbound (currently long-polling; Beta).
- Per-tenant rate limiting on auth-code issuance.
- Auth-code transport via QR code instead of paste (Beta UX).
- Cross-channel identity merging (one user → multiple channels). Each binding is independent for Alpha.
