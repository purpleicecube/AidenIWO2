# ADR-028 — Channel message idempotency scope correction

Date: 2026-04-24
Status: Accepted (Pre-Beta β.5)
Predecessors: ADR-022 (channel layer).
Companions: `IWO3_PRE_BETA_GAP_CLOSURE_PLAN_v0.1.0.md` § β.5.

## Context

α.5 shipped `channel_messages` with the inbound dedup constraint:

```sql
UNIQUE ("channel_kind", "external_message_id")
```

This is the right shape for channels where `external_message_id` is globally unique within a `channel_kind`. **It is the wrong shape for Telegram.** Telegram numbers messages **per chat**: chat A's message #42 and chat B's message #42 are independent. With the original UNIQUE, the second `INSERT … ON CONFLICT DO UPDATE` would silently UPSERT chat B's payload onto chat A's row.

This was caught by the Pre-Beta correctness audit (acceptance criterion #5).

## Decision

### 1. Widen the inbound UNIQUE to (channel_kind, external_chat_id, external_message_id)

Migration `0013_pre_beta_phase_5_channel_inbound_chat_scope.sql`:

```sql
ALTER TABLE channel_messages
  DROP CONSTRAINT IF EXISTS channel_messages_inbound_external_uniq;
ALTER TABLE channel_messages
  ADD CONSTRAINT channel_messages_inbound_external_uniq
  UNIQUE (channel_kind, external_chat_id, external_message_id);
```

The drizzle schema (`db/schema/channel_messages.ts`) is updated to match so future drift is caught by the snapshot test.

### 2. Update `record_inbound_message` ON CONFLICT to match

```sql
ON CONFLICT (channel_kind, external_chat_id, external_message_id)
DO UPDATE SET attempts = channel_messages.attempts + 1,
              payload = EXCLUDED.payload
```

The replay semantics stay intact — same `(chat, message_id)` UPSERTs onto the same row + bumps `attempts`. Only the **scope** changes.

### 3. The outbound idempotency_key UNIQUE stays at (channel_kind, idempotency_key)

The Pre-Beta audit also checked outbound. The `idempotency_key` is application-defined; the Telegram worker writes `f"tg:reply:{chat_id}:{update_id}"` which is already chat-scoped at the application layer. No schema change needed.

### 4. NULL chat ids stay distinct (Postgres semantics)

If a future channel kind has no concept of a chat (broadcast-style), it can leave `external_chat_id` NULL. Postgres treats NULLs as distinct in UNIQUE indexes, so this matches the pre-β.5 (channel_kind, external_message_id) behaviour for those rows.

## Consequences

- Telegram cross-chat collisions cannot alias rows.
- Replay within the same chat is idempotent (same UPSERT behaviour).
- The migration is additive + idempotent; existing Klear/FFAI rows survive untouched.
- Two regression tests added (`test_inbound_uniq_is_chat_scoped_so_message_42_does_not_alias`, `test_inbound_replay_within_same_chat_is_idempotent`) prevent future re-narrowing.

## Out-of-scope (deferred)

- Migrating away from the surrogate `id` PK. Not needed; the UNIQUE is the dedup key, not the PK.
- Per-tenant uniqueness (currently it's per-channel-kind, since chat_ids are global within Telegram). If we ever multi-host the same bot across tenants — which we don't — we'd revisit.
