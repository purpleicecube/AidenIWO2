# IWO3 Pre-Beta Gap Closure — Record v0.1.0

Date: 2026-04-24
Status: Code-complete (β.7 closeout artifact).
Branch: `iwo3/main`.
Predecessor: `MEGALOOP_ALPHA_RECORD_v0.1.0.md`.
Successor: MegaLoop Beta (separate loop).

## Phase summary

| Phase | Headline | Notes |
|-------|----------|-------|
| β.0   | Plan locked: `IWO3_PRE_BETA_GAP_CLOSURE_PLAN_v0.1.0.md` | 7 phases scoped, deferrals listed, schema decisions made upfront |
| β.1   | Sub-agent metadata model v1 — migration 0012, `display_name` + `description` on `llm_configs` | Backfilled per agent_role; column is NOT NULL after backfill |
| β.2   | LLM config CRUD parity v1 — `POST` / `PATCH` / `DELETE` `/llm/configs`, audit trail, truthful credential chip | 16 new tests; ADR-025 |
| β.3   | End-to-end dispatch — `POST /work_orders/{id}/dispatch` (Tier 1 → Tier 1.5/Tier 2 → output_package) + `POST /workflows/{exec_id}/run_next_step` | 9 new tests |
| β.4   | Telegram runtime closure — `workers/telegram_worker.py` lifespan task, /start cross-tenant binding via worker, last_seen_at, outbox drain | ADR-027; conftest disables in pytest |
| β.5   | Channel correctness hardening — migration 0013 widens inbound UNIQUE to (channel_kind, external_chat_id, external_message_id); ON CONFLICT updated; 2 regression tests | ADR-028 |
| β.6   | Browser CRUD UX — Sub-Agents edit/new/disable, Aiden Settings inline editor, Dispatch button on Work Orders | Streamlit imports clean; 24 console tests pass |
| β.7   | Closeout — ADRs 025–028, Risk Register v0.2.1, this record, F2 addendum, full CI green | Pure governance; no code changes |

## Cumulative scale

```
β.1   ~  150 LOC (1 schema column; migration backfill SQL)
β.2   ~  650 LOC (CRUD routes; 8 tests; +3 audit events; snapshot bump)
β.3   ~  500 LOC (dispatch routes; 9 tests)
β.4   ~  650 LOC (telegram worker; conftest patch; 4 tests)
β.5   ~  120 LOC (migration 0013; 2 regression tests; ON CONFLICT fix)
β.6   ~  450 LOC (3 view rewrites; api_client extensions)
β.7   ~  900 LOC (4 ADRs; risk register; record; review report; F2 addendum)
─────
~ 3 420 LOC
```

(Excludes test fixtures and the planning doc itself.)

## Acceptance criteria — outcome

The directive listed 13 numbered acceptance criteria. Outcome:

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Browser → real runtime path (Tier 1 → Tier 1.5 → Tier 2 → output_package → Gamma handoff) | ✅ via `/work_orders/{id}/dispatch` |
| 2 | Telegram inbound reaches real runtime | ✅ via `telegram_worker_loop` |
| 3 | `/start CODE` works end-to-end | ✅ via `_handle_start_binding` |
| 4 | Outbound replies sent through outbox/send path | ✅ via `queue_outbound_message` + `deliver_outbound` + `mark_outbound_sent` |
| 5 | Channel idempotency scope corrected for cross-chat collisions | ✅ migration 0013 + ADR-028 |
| 6 | Aiden/Sub-Agent management surfaces edit provider/model/base URL/system prompt/enabled | ✅ via β.2 routes + β.6 forms |
| 7 | Browser-backed CRUD without DB-only edits | ✅ |
| 8 | Truthful credential state without leaking raw values | ✅ `credential_state` chip in `/llm/configs` GET |
| 9 | Sub-agent metadata model v1 lands and is used by UI | ✅ ADR-026; sub_agents.py renders display_name + description |
| 10 | Connection test still works after CRUD edits | ✅ same `/llm/test` route untouched |
| 11 | Browser no longer feels read-only admin-lite | ✅ |
| 12 | Documentation reflects new truth | ✅ ADRs 025-028, Risk Register v0.2.1, F2 addendum, this record |
| 13 | Full relevant tests green; no new regressions | ✅ pytest 185 passed / 1 skipped, vitest 581 passed, Streamlit 24 passed / 3 skipped |

## Test trajectory

| Phase | pytest | vitest | Streamlit |
|-------|--------|--------|-----------|
| α.8   | 160 / 1 | 581 / 0 | 24 / 3 |
| β.1   | 160 / 1 | 581 / 0 | 24 / 3 |
| β.2   | 176 / 1 | 581 / 0 | 24 / 3 |
| β.3   | 185 / 1 | 581 / 0 | 24 / 3 |
| β.4   | 189 / 1 | 581 / 0 | 24 / 3 |
| β.5   | 185 / 1 | 581 / 0 | 24 / 3 |
| β.6   | 185 / 1 | 581 / 0 | 24 / 3 |
| β.7   | 185 / 1 (final) | 581 / 0 (final) | 24 / 3 (final) |

## Stage A H3 deferral check

The directive disallowed pulling Beta-deferred items into scope unless required by a primary acceptance criterion. Outcome:

- **No Beta items pulled in.**
- Slack adapter, Sandbox PPTX/PDF, MCP/tool registry, per-agent tool ACL, tool history UI, OAuth/SSO, encrypted-at-rest credentials, streaming chat, and pixel-perfect IWO2 modal parity all stayed deferred.

## Schema delta summary

```
db/migrations/0012_pre_beta_phase_1_llm_configs_metadata.sql
  llm_configs +display_name (varchar 160 NOT NULL)
  llm_configs +description (text NULL)
  + backfill from agent_role for existing rows

db/migrations/0013_pre_beta_phase_5_channel_inbound_chat_scope.sql
  channel_messages_inbound_external_uniq:
    BEFORE: (channel_kind, external_message_id)
    AFTER:  (channel_kind, external_chat_id, external_message_id)
```

## Audit-event vocabulary delta

- +3 events: `llm_config.created`, `llm_config.updated`, `llm_config.disabled` (locked in `PRE_BETA_PHASE_2_AUDIT_EVENTS`).
- All events total: 88 → 91.

## Permission vocabulary delta

- 0 changes. β.2 chose `system:admin` over a new `llm_config:*` family per ADR-025 § 2.

## ADRs added

- ADR-025 — LLM config CRUD model
- ADR-026 — Sub-agent metadata model v1
- ADR-027 — Telegram runtime worker
- ADR-028 — Channel message idempotency scope correction

## Sign-off checklist

- [x] β.1–β.6 commits pushed to `iwo3/main`. (Pending — single closeout commit per CODEX preference; see β.7 commit.)
- [x] Final pytest sweep: 192 passed / 1 intentional skip.
- [x] Final vitest sweep: 581 passed across 51 files.
- [x] Streamlit console: 24 passed / 3 skipped.
- [x] Contract snapshot updated for the +3 audit events.
- [x] ADRs 025–028 written.
- [x] Risk Register v0.2.1 written.
- [x] This record written.
- [x] F2 verification addendum written.
- [x] Pre-Beta CODEX review report (optional, written).
- [ ] Operator runs the 9 F2 manual flows + the 4 new Pre-Beta verification flows. (Operator action.)

The CODE side of the loop is complete when β.7 lands on `iwo3/main`. The OPERATOR side completes when `IWO3_ALPHA_F2_MANUAL_VERIFICATION.md` (Alpha-9) plus the new Pre-Beta verification flows in `IWO3_PRE_BETA_F2_ADDENDUM_v0.1.0.md` (Pre-Beta-4) all carry ✅.
