# IWO3 Risk Register v0.2.0

Date: 2026-04-24
Predecessor: v0.1.0 (Loop 9 closeout, residuals captured in `LOOP_9_RECORD.md`).
Closeout: MegaLoop Alpha α.8.

This register tracks active architectural and operational risks for IWO3.
v0.2.0 retires Loop 9 risks resolved by Alpha and adds new risks introduced
by the channel layer + LLM runtime. Severities use the Stage A § G3 scale:
**S0** ship-blocking, **S1** high (track + mitigate next loop), **S2** medium
(monitor), **S3** low (note for the record).

## Active risks

### R-021 [S1] Per-WO LLM token ceiling enforced only at call-time

The 50K-per-WO ceiling is checked before each LLM call, but a misconfigured
retry loop could spend large amounts within a single second before the
51st call hits the gate. Bounded by per-call max_tokens=8192 (≤ 7 calls
to overshoot 50K), so absolute worst case is ~57K tokens for a runaway.

**Mitigation:** Per-call cap caps per-second burst; audit log gives forensic
trail. Beta adds per-tenant override + faster gate (single SUM query is the
slowest step today).

### R-022 [S1] Telegram offset persistence is in-process only

`TelegramAdapter._next_offset` lives in memory. A worker restart re-reads up
to 24h of historical updates from the bot. Re-processing is idempotent
(channel_messages.idempotency_key UNIQUE), but it generates noise audit
rows on restart.

**Mitigation:** Outbound idempotency prevents replay on restart. Beta moves
the offset into per-tenant DB storage; tracked for Loop 10.

### R-023 [S2] Auth-code consume runs on bypass connection

`consume_auth_code_and_bind` is necessarily cross-tenant (the bot doesn't
know the tenant until consume succeeds). Two `lint:bypass-rls-explain`
annotations document why; the lint plugin allow-lists those paths. A
bug in the consume path could write to the wrong tenant.

**Mitigation:** PK + status='pending' guard is the security boundary. All
writes happen inside a single asyncpg transaction. Audit row
`channel_identity.bound` includes both `client_id` and `external_id` for
forensics. PR review checklist requires re-validating the rationale on
every change to `channel/core.py`.

### R-024 [S2] Telegram bot token loss → outbound stall

Per-tenant tokens via env vars. If a token is rotated and the env doesn't
get updated, outbound delivery stalls in `pending`; inbound polling raises
`credential_missing` per-tick.

**Mitigation:** The polling worker logs + skips the tenant for the tick;
the operator sees the failure in the audit log (`channel_message.failed`
metadata.kind="credential_missing"). Beta adds a `/health/channels` route
that surfaces token-resolution errors to the browser.

### R-025 [S2] Workflow launch from chat is deferred to Beta

Telegram `create_wo` for workflow_brief decisions creates a WO but does
not instantiate the workflow_execution. Operators must launch the workflow
from the browser. Friction, not breakage.

**Mitigation:** Reply text instructs the operator to "open the browser to
instantiate the workflow execution"; the WO carries the workflow_template_key
in its metadata for one-click launch.

### R-026 [S3] Tier 2 dispatch_intent path lacks transport injection seam

`channel/intent_dispatcher.dispatch_intent` calls `invoke_aiden_tier_1`
without forwarding a `transport=` kwarg. The route tests skip the live
create_wo path on the dispatcher; α.6 unit tests cover parse + status.

**Mitigation:** Tracked for α.7+ refactor. The route-level test for
`POST /aiden/chat` covers the same code path with mocks via the route's
direct `invoke_aiden_tier_1` call (which DOES forward transport).

### R-027 [S3] CI does not run a full Telegram round-trip

No live Telegram bot is wired into CI. The Telegram adapter is exercised
via httpx MockTransport for inbound + outbound, and the intent parser is
exercised against fixed JSON. End-to-end is verified by F2 manual
verification flows (#5–#9).

**Mitigation:** Mocked CI is intentional per Stage A § A8. F2 verification
is documented in `IWO3_ALPHA_F2_MANUAL_VERIFICATION.md`.

### R-028 [S3] Dev bearer auth is in production for Alpha

`X-IWO3-User` + `X-IWO3-Client` are operator-trusted. Anyone with the
headers can act as that pair. Acceptable for the small internal multi-user
posture (Stage A § F1) but is a hard limit on Alpha distribution.

**Mitigation:** Stage A § D4 explicitly accepts dev bearer for Alpha;
Beta replaces with a signed-token provider. Documented in ADR-024.

## Retired (resolved in MegaLoop Alpha)

### R-013 [S1, retired] LLM provider abstraction had no callers

Resolved by ADR-021 / α.2/3/4 — Aiden / PM / Tier 2 all use
`call_openai_compatible` now.

### R-014 [S1, retired] Channel layer not yet built

Resolved by ADR-022 / α.5 — three tables, RLS, audit vocabulary all live.

### R-015 [S1, retired] Telegram is the mandatory chat surface

Resolved by ADR-023 / α.6 — adapter + intent dispatcher + routes shipped.

### R-016 [S2, retired] Browser console has 6+ placeholder pages

Resolved by α.7 — Chat with Aiden, Sub-Agents, Aiden Settings rewritten
against live runtime; remaining placeholders are within Stage A § D1
budget.

### R-017 [S2, retired] Permission vocabulary frozen at 69 / 213 rows

Intentionally bumped to 72 / 223 in α.6 to add channel RBAC; cardinality
assertions in tests + fixture snapshot updated in lock-step. The "lock
upfront" intent is preserved — bumps require a coupled change.

## Process notes

The register is reviewed at every MegaLoop closeout. v0.3.0 is expected at
the end of Beta (Loop 10/11) and will retire R-021..R-024 if Beta lands
the per-tenant overrides and webhook delivery.
