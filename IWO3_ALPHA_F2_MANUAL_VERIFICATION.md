# IWO3 Alpha — F2 Manual Verification

Date: 2026-04-24
Status: Closeout gate (Stage A § F2). Alpha is not "released" until this document carries 9 ✅.

Audience: Operator running through the live runtime to verify each Alpha capability against a real LLM provider + a real Telegram bot. CI mocks LLM traffic per Stage A § A8; this document is the part CI cannot replace.

## Prerequisites

- FastAPI + Streamlit + Postgres running per `docs/runbooks/operator-runbook-alpha.md`.
- `GROQ_API_KEY` exported in the FastAPI process.
- `TELEGRAM_BOT_TOKEN_KLEAR_AI` exported (or whatever tenant you're verifying).
- Operator login = the seeded Klear owner / admin / operator.

## Flow 1 — Submit Order → Aiden Tier 1 → WO created

1. Operator console → Submit Order.
2. Title: "Render the Klear pricing deck"; type: `content_brief`; priority: medium.
3. Submit.
4. ✅ Verify the WO appears in Work Orders with `correlation_id` reflecting the operator action.
5. ✅ Verify the audit log shows `llm.invoked` for `aiden_tier_1` with `metadata.totalTokens` populated.

## Flow 2 — Chat with Aiden in browser

1. Operator console → Chat with Aiden.
2. Type: "build me a one-page Klear pricing site".
3. Send.
4. ✅ Reply renders provider/model/latency, decision_kind = `work_order_brief` or `workflow_brief`.
5. ✅ Audit log shows `llm.invoked` for `aiden_tier_1`.

## Flow 3 — Sub-Agents page connection-test

1. Operator console → Sub-Agents (logged in as Klear owner).
2. Expand `mark_tier_2`. Click "Run connection test".
3. ✅ Provider+model+latency reported; sample text shown.
4. ✅ Audit log shows `llm_provider.connection_tested` ok=true.

## Flow 4 — Aiden Settings issues an auth code

1. Operator console → Aiden Settings → "Channel auth codes".
2. Channel: `telegram`. TTL: 15 min. Click "Issue code".
3. ✅ A 12-character code displays + instructions text.
4. ✅ Audit log shows `channel_auth_code.issued`.
5. ✅ Direct DB query: `SELECT count(*) FROM channel_auth_codes WHERE status='pending'` returns ≥ 1.

## Flow 5 — Telegram /start binding

1. Open Telegram. DM the tenant's bot.
2. Send `/start <code-from-Flow-4>`.
3. ✅ Bot replies confirming bind.
4. ✅ Operator console → Aiden Settings → "Bound identities" shows the new row with `status=active` and the chat_id.
5. ✅ Audit log shows `channel_identity.bound`.

## Flow 6 — Telegram /status against an existing WO

1. Use the WO id from Flow 1.
2. From the bound chat: `/status <wo-id>`.
3. ✅ Bot replies with WO title, status, priority, type, created_at.
4. ✅ Audit log shows `channel_message.received` + `channel_message.processed`.

## Flow 7 — Telegram create-wo via natural language

1. From the bound chat: `create wo: Render the Q2 Klear pricing summary`.
2. ✅ Bot replies "Created WO …" with assigned_role + priority + Aiden classification timing.
3. ✅ Operator console → Work Orders shows the new WO with `correlation_id="telegram:<chat>"`.
4. ✅ Audit log shows `llm.invoked` (aiden_tier_1) + `channel_message.processed`.

## Flow 8 — Telegram /approve

1. From the bound chat: `/approve <wo-id-from-Flow-7>`.
2. ✅ Bot replies "WO … → completed (via /approve)".
3. ✅ Operator console → Work Order detail shows `status=completed`.
4. ✅ Audit log shows `work_order.transitioned` (or equivalent locked event) for the operator-bound user.

## Flow 9 — Revoke identity → unbound chat blocked

1. Operator console → Aiden Settings → "Bound identities" → click "Revoke" on the row from Flow 5.
2. From the same Telegram chat, send `/status <some-wo>`.
3. ✅ Bot replies with the unbound prompt ("send `/start <code>`").
4. ✅ Audit log shows `channel_identity.revoked` and `channel_message.received` for the post-revoke message.

## Sign-off

```
[ ] Flow 1 ✅
[ ] Flow 2 ✅
[ ] Flow 3 ✅
[ ] Flow 4 ✅
[ ] Flow 5 ✅
[ ] Flow 6 ✅
[ ] Flow 7 ✅
[ ] Flow 8 ✅
[ ] Flow 9 ✅

Operator: ___________________ Date: ___________________
```

When this checklist is complete, Alpha is operator-verified and ready for the Klear.ai pilot tenant per ADR-024.
