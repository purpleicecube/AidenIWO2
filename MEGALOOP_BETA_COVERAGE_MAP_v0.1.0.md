# MegaLoop Beta — Coverage Map v0.1.0

Date: 2026-04-25
Status: Draft for CODEX review (post-architect-feedback edit applied 2026-04-25).

## Edit history

- **2026-04-25 — post-architect-feedback:** Section 4 row "Aiden conversation memory" rewritten to make the in-vs-out boundary explicit: operator-facing chat history (per operator+tenant) IS Beta-1 must-have; agent-side cross-WO memory remains GA-deferred. Aligns with the scope proposal's clarified §B language.
Companion to: `IWO3_MEGALOOP_BETA_SCOPE_PROPOSAL_v0.1.0.md`.

This map shows exactly which roadmap items, deferred ADR items, and open architect questions Beta consumes — and which it intentionally leaves for later.

## Section 1 — Original IWO3 architecture sequence

Source: `WS024_IWO3[Branch]/CLAUDE.md` § Architecture Sequence (15 items).

| # | Roadmap area | Where shipped | Beta status |
|---|---|---|---|
| 1 | Production floor: Node version discipline, typecheck, tests, migrations | Loop 1 | done |
| 2 | Multi-client data + prompt + repository foundation | Loop 2 | done |
| 3 | Work Order, Workflow, output-adapter foundation | Loop 3 | done |
| 4 | Identity + RBAC foundation | Loop 4 | done |
| 5 | Typed contracts | Loop 5 | done |
| 6 | Execution cycle semantics | Loop 6 | done |
| 7 | Terminal transition governance | Loop 6 | done |
| 8 | FastAPI runtime API foundation | Loop 7 | done |
| 9 | Streamlit cloud operator console foundation | Loop 8 / 8.3 | done |
| 10 | Channel communications foundation | α.5 | done |
| 11 | Telegram first adapter | α.6 | done |
| 12 | **Unified artifact delivery: Gamma + local PPTX/PDF** | Loop 9 (Gamma); **Beta (Sandbox PPTX/PDF)** | **Beta consumes** |
| 13 | Preflight split: structural gate vs semantic contract evidence | Loop 9 (partial) | partial — Beta should-have |
| 14 | **Operator diagnosis: stuck-WO diagnosis service, API, UI** | partial via γ.4 | **Beta should-have** |
| 15 | **Slack adapter using same channel layer** | foundation in α.5/6 | **Beta consumes** |

## Section 2 — ADR-024 deferred-list reconciliation

Source: `docs/adr/ADR-024_alpha-release-definition.md` § "Deferred to Beta or later".

| Deferred item | Beta status | Notes |
|---|---|---|
| **Sandbox PPTX/PDF live render** | **Beta must-have** | C1 deferral consumed |
| Workflow launch from Telegram | Beta should-have or carry | partially closes via cross-session context (Q7) |
| Webhook-based channel inbound | **Beta must-have** | required for Slack |
| Per-tenant LLM ceiling overrides | **Beta must-have** | Q1 |
| **Production auth** | **Beta must-have** | Q2 |
| Streaming LLM responses | carry to GA | not Beta |
| Multi-channel identity merging | carry to GA | not Beta |
| Cost-aware provider arbitration | optional Beta should-have | Q4 default no |
| Aiden conversation memory | operator-facing chat history per (operator, tenant) is Beta-1 must-have via Q7; agent-side cross-WO memory (Munninn-style) stays GA-deferred | clarified post-feedback 2026-04-25 |

## Section 3 — Carried-question coverage

Source: `IWO3_PRE_BETA_GAP_CLOSURE_CODEX_REVIEW_REPORT_v0.1.0.md` + `CLAUDE_HANDBACK_PRE_BETA_DELTA_2026-04-25.md`.

The 8 carried questions plus 3 from δ — all tracked in `IWO3_MEGALOOP_BETA_PRESTART_QUESTIONS_v0.1.0.md`.

| # | Question | Beta scope | Prestart Q# |
|---|---|---|---|
| 1 | Per-tenant LLM ceiling override | must-have | Q1 |
| 2 | Beta auth choice | must-have | Q2 |
| 3 | Channel webhook endpoint | must-have | Q3 |
| 4 | Cost-aware provider arbitration | optional should-have | Q4 |
| 5 | RBAC granularity for config CRUD | must-have | Q5 |
| 6 | Persona library / template profiles | should-have | Q6 |
| 7 | Cross-session chat context durability | must-have | Q7 |
| 8 | Server-side WO idempotency | must-have | Q8 |
| 9 | Workspace file content fetch (δ) | must-have | Q9 |
| 10 | Workspace hard-delete (δ) | must-have | Q10 |
| 11 | Per-operator scratch (δ) | should-have | Q11 |

## Section 4 — Theme alignment from directive

Source: directive § "REQUIRED BETA THEMES TO CONSIDER" (9 items).

| Theme | Beta status | Where in scope |
|---|---|---|
| 1. Unified artifact delivery maturity | **Beta must-have (Sandbox PPTX/PDF live)** | scope §C must-have |
| 2. Sandbox PPTX/PDF live path | **Beta must-have** | scope §C must-have |
| 3. Slack adapter / second channel | **Beta must-have** | scope §C must-have |
| 4. Stronger workspace semantics | partial — Beta must-have on content fetch + hard-delete; should-have on per-operator scratch | scope §C |
| 5. Aiden conversational/product maturity | should-have on persona library + conversational v2 | scope §C should-have |
| 6. Tool/MCP registry direction | **Beta must-have on shape; not execution** | scope §C must-have |
| 7. Production-hardening / auth / credentials | **Beta must-have** | scope §C must-have (multiple items) |
| 8. Cross-session context durability | **Beta must-have** | scope §C must-have |
| 9. Server-side WO idempotency | **Beta must-have** | scope §C must-have |

All 9 themes addressed; 7 must-have, 2 should-have or partial.

## Section 5 — Loop-by-loop Beta consumption

If the architect picks the recommended split (Q12 default = b):

### Beta-1 (Production Posture) consumes

- Roadmap: production-hardening (not numbered), preflight split partial (#13)
- ADR-024 deferred: production auth, webhook ingress, per-tenant ceiling overrides
- Carried questions: Q1, Q2, Q3, Q5, Q7, Q8
- Loop δ questions: Q9, Q10
- Themes: #4, #7, #8, #9

Beta-1 close gates: 9 production-grade gates per scope §F items 1, 5, 6, 7, 8, 9, 11, 12 and partial 10.

### Beta-2 (Capability Expansion) consumes

- Roadmap: #12 (Sandbox PPTX/PDF), #14 (operator diagnosis), #15 (Slack adapter)
- ADR-024 deferred: Sandbox PPTX/PDF live, (workflow launch from chat — partial)
- Carried questions: Q4 (optional), Q6 (persona library), Q11 (per-operator scratch)
- Themes: #1, #2, #3, #5, #6

Beta-2 close gates: scope §F items 3, 4, 10 (full) plus the should-haves that were deferred from Beta-1.

### If single-loop Beta is chosen (Q12 = a)

All of the above merges into one ~14-must-have loop with internal phases ~β.1 through β.14 + closeout. Sequencing within the loop still respects the dependency order: production posture before capability expansion.

## Section 6 — What is **not** in Beta

Listed for clarity so reviewer can confirm.

- Streaming LLM responses (request/response only canonical).
- Live MCP/tool **execution** (registry shape only).
- Cost-aware provider arbitration runtime logic (optional should-have on registry shape only).
- Cross-channel identity merging.
- Multi-region / HA / DR.
- Pixel-perfect IWO2 modal parity.
- Telegram offset durable persistence (R-022; carried).
- Aiden conversation memory beyond per-session (Beta-1 covers cross-session per (operator, tenant); beyond that is GA).
- Per-tenant deployment_mode beyond `shared_multi_tenant` (Loop 13+).
- Replit handoff bundles (Alpha-era IWO2 lineage; not relevant to Beta).

## Section 7 — Closeout artifact set anticipated

For the recommended split:

- Beta-1: `IWO3_MEGALOOP_BETA_1_RECORD_v0.1.0.md`, ADRs (auth, encrypted creds, webhook, idempotency, ceiling, RBAC granularity, workspace content/delete, cross-session chat), Risk Register v0.3.0 partial.
- Beta-2: `IWO3_MEGALOOP_BETA_2_RECORD_v0.1.0.md`, ADRs (Slack, Sandbox, MCP registry, persona library, conversational v2), Risk Register v0.3.0 final.
- Combined: `MEGALOOP_BETA_RECORD_v0.1.0.md` capping both halves; CODEX review report.

Single-loop alternative folds these into one record + one ADR pack + one Risk Register update.

## Conclusion

Beta covers **the production-pilot-ready maturity layer plus second-channel + second-output-adapter expansion**. It explicitly leaves GA-grade durability, streaming, multi-region, and full tool-execution out of scope.

Coverage is honest: 9 of 9 directive themes + 11 of 11 carried questions + 5 of 5 ADR-024 Beta-eligible deferred items are routed to scope buckets with rationale.

R-034 stays operational caveat per architect 2026-04-25.
