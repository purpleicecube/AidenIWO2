# IWO3 Pre-Beta F2 Verification — Addendum v0.1.0

Date: 2026-04-24
Status: Closeout gate (Pre-Beta β.7).
Predecessor: `IWO3_ALPHA_F2_MANUAL_VERIFICATION.md` (Alpha-9 flows).

This addendum adds 4 new verification flows that exercise the Pre-Beta β closure work. The original 9 Alpha flows still apply and must be re-run to verify nothing regressed.

## Pre-Beta-1 — End-to-end dispatch from browser

1. Operator console → Submit Order. Title: "Render the Klear Q2 pricing summary"; type: `content_brief`; priority: medium.
2. Operator console → Work Orders → expand the new WO → click **"Run Aiden + Tier 2"**.
3. ✅ Reply renders `decision_kind = work_order_brief` and an output_package id.
4. ✅ Operator console → Output Packages — the new package appears with the correct title.
5. ✅ Audit Log shows: `llm.invoked` (aiden_tier_1), `llm.invoked` (tier 2 role), `output_package.created`, `work_order.transitioned` (pending → processing).

## Pre-Beta-2 — Sub-Agent CRUD

1. Operator console → Sub-Agents (logged in as Klear owner).
2. Expand any agent → Edit tab → change `display_name` → Save.
3. ✅ Page rerenders with the new display_name.
4. ✅ Audit log shows `llm_config.updated` with `fieldsChanged: ["display_name", ...]`.
5. Sub-Agents → New sub-agent → fill agent_role `test_demo_role`, display_name "Demo", provider Groq, model `openai/gpt-oss-120b`, credential_ref `credential_ref:env:GROQ_API_KEY` → Create.
6. ✅ New row appears.
7. ✅ Audit log shows `llm_config.created`.
8. Disable tab → click Disable.
9. ✅ Row chip turns ⚪; row stays in list (soft delete).
10. ✅ Audit log shows `llm_config.disabled` with `hardDelete: false`.

## Pre-Beta-3 — Telegram worker live

1. Verify `TELEGRAM_BOT_TOKEN_KLEAR_AI` exported in the FastAPI process; restart if not.
2. Issue a fresh auth code via Aiden Settings.
3. From Telegram, DM the bot `/start <code>`.
4. ✅ Bot replies "✅ Bound" within ~10s (the worker tick).
5. Send `create wo: Render the Q3 Klear pricing summary`.
6. ✅ Bot replies "Created WO …" with assigned_role + priority.
7. ✅ Operator console → Work Orders shows the new row with `correlation_id="telegram:<chat>"`.
8. ✅ Operator console → Aiden Settings → Bound identities — `last_seen_at` updates after each message.
9. ✅ Audit log shows: `channel_message.received`, `llm.invoked`, `work_order.created`, `channel_message.processed`, `channel_message.send_queued`, `channel_message.sent`.

## Pre-Beta-4 — Cross-chat collision regression

1. From a SECOND Telegram chat (different chat_id), bind via /start with a new auth code.
2. From chat A, send a message (the Bot remembers chat_id but Telegram's message_id starts low for each chat).
3. Open psql against the DB:
   ```
   SELECT count(*) FROM channel_messages
    WHERE channel_kind = 'telegram'::channel_kind
      AND external_chat_id IN ('<chat_a>', '<chat_b>');
   ```
4. ✅ Each chat's messages are distinct rows. (Pre-β.5 the second chat's first message would have UPSERTed onto chat A's first message.)

## Sign-off

```
[ ] Pre-Beta-1 ✅
[ ] Pre-Beta-2 ✅
[ ] Pre-Beta-3 ✅
[ ] Pre-Beta-4 ✅

Plus all 9 original Alpha F2 flows re-verified:
[ ] Alpha-1..9 ✅ (no regressions)

Operator: ___________________ Date: ___________________
```

When this checklist plus the original 9 Alpha flows are all ✅, IWO3 is at the credible Beta-entry baseline the Pre-Beta directive defined.
