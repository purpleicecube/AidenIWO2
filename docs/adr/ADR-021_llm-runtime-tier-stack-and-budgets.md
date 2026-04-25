# ADR-021 — LLM provider runtime, Tier 1/1.5/2 stack, per-WO token budgets

Date: 2026-04-24
Status: Accepted (MegaLoop Alpha α.2 / α.3 / α.4)
Predecessors: ADR-014 (RBAC), ADR-018 (FastAPI runtime), ADR-020 (live adapter dual gate).
Companions: `IWO3_ALPHA_PRESTART_DECISIONS_v0.1.0.md` (Stage A § A1/A2/A5/A7), Stage A audit-event lock (`ALPHA_PHASE_A2_AUDIT_EVENTS`).

## Context

Loop 9 Phase 9.3 shipped the LLM provider abstraction (`call_openai_compatible`) and the per-tenant `llm_configs` table, but no caller code in the runtime actually used them. The Aiden Tier 1 / PM Tier 1.5 / Tier 2 sub-agent classes that shape the IWO product still ran as IWO2-shaped TypeScript/PocketFlow code outside the IWO3 FastAPI process. MegaLoop Alpha had to bring the three tiers onto the IWO3 runtime so the operator console + Telegram + the Submit Order flow all spend tokens through the same gate, write the same audit rows, and obey the same per-tenant ceilings.

Stage A locked four constraints upfront:

- **A1.** All three tiers must be live in Alpha (no "Tier 2 deferred to Beta" cop-out).
- **A2.** Groq + OpenRouter are mandatory; OpenAI is registered but not wired for normal flow in Alpha.
- **A5.** Tier 1 / Tier 1.5 emit strict JSON; Tier 2 emits markdown plus a JSON metadata envelope.
- **A7.** Per-call `max_tokens=8192`, per-WO ceiling = 50 000 tokens, 1 retry on 429.

## Decision

### 1. Three-tier runtime architecture

```
intake_text  ── Aiden Tier 1 ─▶ AidenDecision { kind: brief | workflow | clarification }
                    │
                    ├─ work_order_brief  ─▶ Tier 2 sub-agent (Mark/Tom/Hank/Paul)
                    │                       └─ markdown + metadata envelope
                    │
                    └─ workflow_brief   ─▶ Tier 1.5 PM
                                            └─ workflow_execution + ordered step plan
                                                └─ each step → Tier 2 sub-agent
```

Each tier is a single Python module under `apps/api-fastapi/runtime/`:

- `runtime/tier_1_aiden.py` — `invoke_aiden_tier_1(...)`.
- `runtime/tier_1_5_pm.py` — `instantiate_workflow_from_brief(...)`.
- `runtime/tier_2_subagents.py` — `invoke_tier_2(...)`, `produce_output_package(...)`, `execute_step_run(...)`.

Each tier resolves its config via `llm.config_resolver.resolve_llm_config(conn, client_id, agent_role)` against the seeded roles (`aiden_tier_1`, `pm_tier_15`, `mark_tier_2`, `tom_tier_2`, `hank_tier_2`, `paul_tier_2`). All providers go through `call_openai_compatible` so we have one HTTP path to instrument, one credential resolver to audit, and one place to inject httpx transports for tests.

### 2. Strict JSON for routing tiers

Aiden Tier 1 returns a typed `AidenDecision` parsed by `_parse_decision`. The provider call sets `response_format={"type": "json_object"}` when supported (Groq + OpenAI Compatible servers). Malformed JSON raises `AidenDecisionMalformed` and writes `llm.failed`; the dispatcher converts that to a friendly chat reply. The PM Tier 1.5 elaborator uses the same envelope; Tier 2 deliverables flow through `Tier2OutputEnvelope` (content_markdown + summary + output_kind + metadata) and become `output_packages` rows.

### 3. Per-WO token ceiling — `runtime/budgets.py`

A pre-flight check (`check_or_raise_wo_budget`) sums `metadata->>'totalTokens'` across `llm.invoked` audit rows for the current `workOrderId` and raises `LlmBudgetExceeded` when the next call's char-based estimate would breach `DEFAULT_PER_WO_CEILING = 50_000`. The exception writes `llm.budget_exceeded` and the caller surfaces a friendly error. The audit-log query is the storage: there is no separate `llm_token_usage` table to keep coherent. This trades one DB read per call for zero schema sprawl, which is the right call for Alpha given the volume and the fact that the audit log is already RLS-scoped.

### 4. CI mocks all LLM traffic

The runtime modules accept `transport: httpx.MockTransport | None`. Tests inject mocks through that seam; CI sets no provider keys. The route tests therefore exercise the credential-missing failure path (200 ok=false) and the parse path independently from any network. The production code path is exactly the same code, with the transport defaulted to None — the only change between test and prod is a constructor parameter.

### 5. RBAC alignment

Aiden Tier 1 is invoked from contexts that require `work_order:create` (Submit Order, Chat with Aiden) or are operator-bound (Telegram inbound dispatch). Tier 1.5 + Tier 2 are invoked transitively from those entry points, so their permissions are the entry-point's. There is no separate `aiden:invoke` permission — the gate is the work-product gate.

## Consequences

- Adding a new sub-agent is a constant-cost change: insert a new `llm_configs` row, register the role in `KNOWN_TIER_2_ROLES` / `NORMALIZE_TIER_2`, and write a system prompt.
- Adding a new provider is a constant-cost change in `llm/providers.py`'s `callable_providers()` set.
- The per-WO ceiling is enforced exclusively at call-time, not at run-time. A misconfigured retry loop could blow past 50K within a single second; the fail-fast on the 50,001st token is the only line of defense. We accept this for Alpha because (a) the per-call cap of 8192 makes overshoot bounded, and (b) the audit log is the source of truth, so any breach is forensic.
- Scaling the ceiling requires touching one constant. Per-tenant overrides are deferred to Beta (one column on `clients`, no schema invention).
- The Aiden system prompt lives in `runtime/tier_1_aiden.AIDEN_SYSTEM_PROMPT` for Alpha. Promoting it to a `prompt_profile` with versioned overrides is a Beta concern — Alpha gets us through the contract validation phase first.

## Out-of-scope (deferred)

- Per-tenant ceiling overrides (Beta).
- Streaming responses (Beta — Alpha is request/response only).
- Aiden conversation memory across messages (Beta — Chat with Aiden currently treats each turn as fresh).
- Cost-aware provider arbitration (Loop 11+).
- Tier 2 mock fallbacks for offline runs (currently dispatch_intent's create_wo path is documented as needing a transport seam; deferred per α.6 test plan).
