# ADR-024 — IWO3 Alpha release definition (what's in, what's out)

Date: 2026-04-24
Status: Accepted (MegaLoop Alpha α.8 closeout)
Predecessors: ADR-021 (LLM runtime), ADR-022 (channel layer), ADR-023 (Telegram adapter).
Companions: `IWO3_ALPHA_PRESTART_DECISIONS_v0.1.0.md` (Stage A locked decisions), `MEGALOOP_ALPHA_RECORD_v0.1.0.md`, `MEGALOOP_ALPHA_COVERAGE_MAP_v0.1.0.md`.

## Context

Stage A locked the Alpha scope as a single MegaLoop with 8 internal phases (α.1–α.8). The release-definition decision is: when α.8 is green, what does it mean to call IWO3 "Alpha"? This ADR is the contract IWO3 Alpha consumers (Klear.ai pilot, FreedomForge.ai dev tenant, internal operators) read before taking a dependency.

## Decision — IWO3 Alpha capabilities

### Live and supported

1. **Three-tier runtime** (ADR-021): Aiden Tier 1, PM Tier 1.5, Tier 2 sub-agents (Mark / Tom / Hank / Paul) all run against real LLM providers (Groq, OpenRouter). Per-WO token ceilings + per-call max_tokens enforced.
2. **Telegram chat surface** (ADR-023): per-tenant bot, inbound + outbound, /start binding, /status, create-wo (slash + natural language), /approve, /reopen, /unblock.
3. **Channel layer** (ADR-022): identities, auth codes, messages outbox, polling worker, RLS-enforced everywhere.
4. **Browser operator console** with 12+ live pages: Dashboard, Submit Order, Work Orders, Workflows, Output Packages, Output Handoffs, Audit Log, Adapter Credentials, Aiden Settings, Sub-Agents, Chat with Aiden, Tenant picker. Up to 6 placeholder pages remain (Stage A § D1 budget).
5. **Gamma live render** (ADR-020): dual-gate (env + first-invocation), async polling with watchdog, terminal-cascade WO completion.
6. **RBAC + RLS posture** (ADR-014/015): 72-key permission vocabulary, role-permission seed, per-row RLS on every tenant table including the new channel tables.
7. **Audit log**: 88 locked event names; every state change + every LLM call + every channel message writes a row; queryable by WO + tenant from the browser.
8. **Dev bearer auth** (Stage A § D4): X-IWO3-User + X-IWO3-Client headers carry the principal pair. Production auth is Beta.

### Deferred to Beta or later (out of Alpha)

- **Sandbox PPTX/PDF live render** (Stage A § C1 → Beta / Loop 10).
- **Workflow launch from Telegram** (Stage A § B2 → Beta).
- **Webhook-based channel inbound** (long-polling only in Alpha).
- **Per-tenant LLM token-ceiling overrides** (constant-only for now).
- **Production auth** (Replit OAuth or equivalent — Stage A § D4 deferred).
- **Streaming LLM responses** (request/response only).
- **Multi-channel identity merging** (each binding independent).
- **Cost-aware provider arbitration** (Loop 11+).
- **Aiden conversation memory across messages**.

## Operator runbook gates

Before calling Alpha "released" the operator runs the 9 manual verification flows in `IWO3_ALPHA_F2_MANUAL_VERIFICATION.md`:

1. Submit Order → Aiden Tier 1 classification → WO created (browser).
2. Chat with Aiden → live LLM decision in browser.
3. Sub-Agents page → connection-test against Groq for `mark_tier_2`.
4. Aiden Settings → issue Telegram auth code → verify it appears in `channel_auth_codes`.
5. Telegram `/start CODE` from a real bot → identity binds, audit row written.
6. Telegram `/status <wo>` against an existing WO → reply formatted.
7. Telegram `create wo: …` → Aiden Tier 1 fires, WO created with `correlation_id="telegram:<chat>"`.
8. Telegram `/approve <wo>` → WO transitions to `completed`, audit row written.
9. Browser → revoke the Telegram identity → next inbound message is rejected with "send /start CODE".

Any failed flow blocks Alpha promotion.

## CI gates

α.8 closeout requires green CI on:

- `pytest -q` (currently 160 passed, 1 skipped).
- `npx vitest run` (currently 581 passed across 51 files).
- ESLint custom rules (`require-tenant-scope-on-client-tables`, `no-raw-audit-insert`).
- Contract snapshot freeze (`tests/fixtures/contract-enums.snapshot.json`).

## Consequences

- Alpha is operator-only by design. No public traffic, no public webhook.
- Alpha tenants can be brought up by env config + DB seed; no application code change.
- The release contract is enforced by ADRs + lock files. Drifting any cardinality (permissions, audit events, enums) without bumping the snapshot fails CI.
- Any new live capability (Sandbox / Slack / streaming) lands behind a fresh ADR + a per-feature env flag, mirroring ADR-020's gate pattern.
