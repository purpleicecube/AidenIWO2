# MegaLoop Alpha Coverage Map v0.1.0

Date: 2026-04-24
Status: Final (α.8 closeout artifact)
Scope: Maps each Stage A locked decision to the artifacts that fulfilled it.

## Stage A § A — LLM runtime

| Decision | Locked value                                                 | Artifact(s)                                                                   |
| -------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| A1       | All three tiers live in Alpha                                | ADR-021; `runtime/tier_1_aiden.py`, `runtime/tier_1_5_pm.py`, `runtime/tier_2_subagents.py`. |
| A2       | Groq + OpenRouter mandatory; OpenAI registered-not-Alpha     | `llm/providers.py` (`callable_providers()`), `db/seeds/llm_configs.json`.     |
| A4       | Runtime-first; Chat with Aiden by closeout                   | `routes/aiden.py`, `apps/console-streamlit/views/chat.py`.                    |
| A5       | Strict JSON for Tier 1/1.5; markdown + JSON envelope for T2  | `runtime/tier_1_aiden._parse_decision`, `tier_2_subagents.Tier2OutputEnvelope`. |
| A7       | per-call max_tokens=8192, per-WO ceiling=50K, 1 retry on 429 | `runtime/budgets.py` (constants + `check_or_raise_wo_budget`).                |
| A8       | CI mocks all LLM traffic                                     | All test files use `httpx.MockTransport`; no provider keys in CI.             |

## Stage A § B — Channel + Telegram

| Decision | Locked value                                                 | Artifact(s)                                                                   |
| -------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| B1       | Telegram mandatory                                           | ADR-023; `channel/telegram.py` (`TelegramAdapter`).                           |
| B2       | create WO + status + approve/reopen/unblock; workflow launch deferred | `channel/intent_dispatcher.py` (`dispatch_intent`); `views/workflows.py` covers browser launch. |
| B4       | per-tenant bot tokens via `credential_ref:env:TELEGRAM_BOT_TOKEN_*` | `channel/telegram.env_var_for_telegram_bot_token`, `resolve_bot_token`.      |
| B5       | channel_messages table + audit mirror                        | ADR-022; `db/migrations/0010_alpha_phase_5_channel_layer.sql`; `channel/core.py` outbound + inbound. |
| B7       | `/start <auth_code>` + channel_identities binding            | `channel/core.consume_auth_code_and_bind`; `routes/channels.issue_channel_auth_code`. |

## Stage A § C — Sandbox PPTX/PDF

| Decision | Locked value           | Artifact(s)                                                                |
| -------- | ---------------------- | -------------------------------------------------------------------------- |
| C1       | Sandbox PPTX/PDF = Beta | Out-of-scope for Alpha; documented in ADR-024 deferred list.               |

## Stage A § D — Browser surface

| Decision | Locked value                                       | Artifact(s)                                                                   |
| -------- | -------------------------------------------------- | ----------------------------------------------------------------------------- |
| D1       | 12 must-be-live pages, ≤6 placeholder OK           | `apps/console-streamlit/views/` (12 live: Dashboard, Submit Order, Work Orders, Workflows, Output Packages, Output Handoffs, Audit Log, Adapter Credentials, Aiden Settings, Sub-Agents, Chat with Aiden, Tenants). Placeholders: Sandbox, Design Lab partial, System Health, Tier Overview, Pipelines, User Management. |
| D4       | Dev bearer auth for Alpha                          | `deps.current_user_context` (X-IWO3-User + X-IWO3-Client); ADR-024.           |

## Stage A § F — Posture

| Decision | Locked value                            | Artifact(s)                                                                   |
| -------- | --------------------------------------- | ----------------------------------------------------------------------------- |
| F1       | Small internal multi-user usable        | Tested via 9 F2 manual verification flows.                                    |
| F2       | 9 manual verification flows mandatory   | `IWO3_ALPHA_F2_MANUAL_VERIFICATION.md` (closeout artifact).                   |

## Stage A § G — Governance

| Decision | Locked value                                                 | Artifact(s)                                                                   |
| -------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| G3       | Risk Register bumps to v0.2.0 at Alpha closeout              | `RISK_REGISTER_v0.2.0.md`.                                                    |
| G4       | MegaLoop Record canonical + LOOP_10/11/12_RECORD stubs       | `MEGALOOP_ALPHA_RECORD_v0.1.0.md`, `LOOP_10_RECORD.md`, `LOOP_11_RECORD.md`, `LOOP_12_RECORD.md`. |

## Stage A § H — Mid-flight deferral

| Decision | Locked value                                                                   | Artifact(s)                                                                   |
| -------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| H3       | One-criterion mid-flight deferral allowed BUT NOT for live tiers / Telegram inbound+create+status / Gamma live / RBAC+audit / must-be-live browser surfaces | No deferral exercised in Alpha. All hard-locked criteria shipped.             |

## Audit-event vocabulary (locked)

| Phase pack                       | Count | Source                                              |
| -------------------------------- | ----- | --------------------------------------------------- |
| ALPHA_PHASE_A2_AUDIT_EVENTS      | 1     | `llm.budget_exceeded`                               |
| ALPHA_PHASE_A5_AUDIT_EVENTS      | 8     | `channel_*` (auth_code, identity, message lifecycle)|
| Total ALL audit events           | 88    | `tests/fixtures/contract-enums.snapshot.json`       |

## Permission vocabulary (locked)

| Item                            | Before α | After α | Notes                                |
| ------------------------------- | -------- | ------- | ------------------------------------ |
| permissions.permission_key total | 69       | 72      | +3 channel RBAC keys.                |
| role_permissions rows total     | 213      | 223     | +10 role-permission seed rows.       |
| owner role permissions          | 69       | 72      | All 3 channel keys.                  |
| admin role permissions          | 67       | 70      | All 3 channel keys.                  |
| operator role permissions       | 27       | 29      | issue + read.                        |
| reviewer role permissions       | 17       | 18      | read.                                |
| viewer role permissions         | 13       | 13      | unchanged.                           |
| agent_system role permissions   | 20       | 21      | read.                                |

## Migration count

| Migration                                                      | Phase   |
| -------------------------------------------------------------- | ------- |
| 0010_alpha_phase_5_channel_layer.sql                           | α.5     |
| 0011_alpha_phase_6_channel_permissions.sql                     | α.6     |

## Test cardinalities at α.8 closeout

| Suite          | Result                                |
| -------------- | ------------------------------------- |
| pytest         | 160 passed, 1 skipped (3 warnings)    |
| vitest         | 581 passed across 51 test files       |
| Streamlit tests | 24 passed, 3 skipped                 |
| ESLint custom rules | clean (require-tenant-scope, no-raw-audit-insert) |
