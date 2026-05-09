# ADR-033 — Memory V2 runtime breadth (Loop Lambda)

Date: 2026-05-09
Status: Accepted (Loop Lambda closeout).
**Relationship to ADR-031 + ADR-032: extends, does not supersede.**
ADR-031's five-layer firewall + single-builder + 2K-budget locks remain
binding for Tier-1 chat. ADR-032's parser → assembler-extension surface
+ canonical_facts hybrid remain binding for V1.5. ADR-033 only adds
two thin **wrappers** over `memory_context_builder` for two new
readers (PM, Tier-2) and a `surface` discriminator on audit metadata.
Every guarantee from ADR-031/-032 is preserved verbatim — re-asserted
explicitly in §"Architectural locks honored" below.

Predecessors: ADR-031, ADR-032, ADR-029 (Beta-1 production posture
— per-WO 50K ceiling + chat_sessions). Companions:
`WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_LAMBDA_SCOPE_PROPOSAL_v0.1.0.md`,
`IWO3_MEMORY_PARITY_MATRIX_v0.1.0.md`.

## Context

Loop Iota shipped Memory V1 — Tier-1 chat memory only. Loop Kappa
shipped Memory V1.5 — Tier-1 chat operational maturity (path/filename/
folder retrieval + canonical_facts CRUD + ops surface + CI gate).
Both are Tier-1-chat-scoped.

Memory parity matrix rows 8, 9, 10 are still open — Tier-1.5 PM
elaboration, Tier-2 sub-agent invocation, and WO/WF execution paths
all run amnesic at the LLM boundary. Operators who set canonical
facts via the Kappa CRUD UI see them in chat but NOT in WO
deliverables (Mark, Tom, Hank, Paul, Jamie, Nyx, Polaris, Darla,
SOP-Master). That gap is the primary source of "I told Aiden the
pricing — why is the deck wrong?" friction.

## Decision

Ship Memory V2 as **two thin wrappers + a per-call surface
discriminator + per-call budget kwarg on the central builder**.
No new SQL. No new tables. No new event names. Every memory bundle
still flows through `memory_context_builder` and through the five-
layer firewall.

### Two wrappers (not parallel assemblers)

`apps/api-fastapi/memory/wrappers.py` exposes:

```python
async def memory_context_builder_for_workflow(
    conn, *, client_id, work_order_id, workflow_execution_id,
    intake_text, actor_user_id=None,
) -> MemoryBundle: ...

async def memory_context_builder_for_subagent(
    conn, *, client_id, work_order_id, sub_agent_role,
    intake_text, actor_user_id=None,
) -> MemoryBundle: ...
```

Both wrappers:

1. Resolve operator identity (actor → WO submitter → sentinel).
2. Build extra audit metadata
   (`work_order_id`, `workflow_execution_id`, `sub_agent_role`).
3. Delegate to `memory_context_builder` with the per-surface budget
   and surface tag.

The wrappers have NO independent SQL, NO independent validation, and
NO independent audit pipeline. They are convenience surfaces — not
parallel paths.

### Per-surface budget (D-L1 default, accepted)

| Surface                   | Budget (tokens) | Rationale                                                               |
|---------------------------|----------------:|-------------------------------------------------------------------------|
| Tier-1 chat (`aiden_chat`) |           2,000 | Unchanged from Iota; operators converse with rich context              |
| Tier-1.5 PM elaboration   |           1,500 | PM prompt is shorter than Aiden's; needs canonical facts + 1-2 hits   |
| Tier-2 sub-agent (per call) |         1,500 | Tier-2 prompt already carries WO payload; compress chat (don't need)  |

A 5-step workflow execution emits 1 PM + 5 Tier-2 = 6 bundles ×
1.5K = 9K of memory total. Under the 50K WO ceiling locked in
Beta-1 ε.1 (ADR-029 §Q1) by ~5x.

Per-call budgets (not a shared per-WO scheduler) keep each
invocation deterministic. Shared pool would require allocation
scheduling that does not exist.

### Bundle reuse policy (D-L2 default, accepted)

**Fresh assembly per Tier-2 invocation.** The wrapper does NOT
propagate a Tier-1 chat bundle. The Tier-2 intake is the WO
description (or step input payload), NOT the operator's chat
message. Different intake → different retrieval signals → fresh
assembly is the correct semantics.

Cost: ~5–10ms per Tier-2 invocation (single composite query, same
budget as Iota). For a 5-step workflow, total memory-assembly cost
is ~30–60ms — negligible compared to the multi-second LLM call
latencies.

### Audit posture (D-L3 default, accepted)

**Same `memory.applied` event with a new `surface` discriminator
field.** Values:

- `"chat"` — Tier-1 (default for backward compatibility)
- `"tier_1_5_pm"` — PM elaboration
- `"tier_2_subagent"` — Tier-2 sub-agent invocation

The Tier-2 case adds `sub_agent_role` and `work_order_id` to
metadata. The Tier-1.5 case adds `workflow_execution_id`. The
audit row's `target_type` becomes `"memory_bundle"` (instead of
`"chat_session"`) for the new surfaces so downstream queries can
distinguish at the indexed column level.

Cardinality estimate: a workflow execution with 5 Tier-2 steps emits
1 (PM) + 5 (Tier-2) = 6 `memory.applied` rows on top of the
original 1 chat-side row = 7x baseline. Acceptable: each row is
small, RLS-scoped, and writes are batched within the FastAPI
request (already a P0 optimization in the Iota performance budget
note).

The smoke alarm `memory.source_rejected` stays one event regardless
of surface — the alarm doesn't care which reader tripped it.

### Operator identity for async WO/WF execution (D-L4 with deviation)

**Spec said:** `work_orders.created_by_user_id` is the canonical
async operator identity. Migration 0027 backfills NULL rows then
enforces NOT NULL.

**Codebase reality:** `work_orders.created_by_user_id` does NOT
exist. The actual column is `work_orders.submitted_by_user_id`
(nullable). Lambda proceeds with the actual column and tolerates
NULL via a sentinel UUID.

**Implementation:**

- The wrapper looks up `work_orders.submitted_by_user_id` for the
  given `work_order_id`. If present, that's the operator identity.
- If NULL, the wrapper substitutes a sentinel UUID
  `00000000-0000-4000-8000-0000000fffff`. This identity has no
  client_membership row anywhere; Layer 4 validator's
  `owner_user_id` check therefore rejects any `scratch_retrieval`
  source — scratch is silently skipped for WOs without a recorded
  submitter. Tenant-wide retrieval still active.
- Migration 0027 is **NOT** filed in this loop. NOT NULL enforcement
  is deferred until a real operational need surfaces (e.g., when
  scratch-retrieval misses become a reported issue).

Deviation rationale: the spec was authored against an assumed
schema; correctness wins over schema-rename cosmetics. The behavior
preserves per-operator isolation (matrix row 13 — IWO3 stronger
than IWO2 here) without requiring a column-rename migration.

### Lint posture (no new rule)

`tools/eslint-plugin-iwo3/rules/no-direct-llm-content-injection.ts`
already covers the central memory builder import requirement. The
rule's allowlist includes `memory/` package + `routes/aiden.py` +
`tests/`. Lambda's wrappers live in `memory/wrappers.py` (allowlisted
by the existing rule), and the new invocation sites
(`routes/dispatch.py`, `workers/wo_dispatch_worker.py`) call the
wrappers via standard imports — no new lint rule required.

If a future contributor tries to inject `memory_block=<literal>`
into `invoke_tier_2` or `instantiate_workflow_from_brief` from a
file that does NOT import from `memory`, the existing heuristic
will flag it. **This was a deliberate test of the lint rule's
generality** — and it held without modification.

## Architectural locks honored

1. **One central memory builder** (ADR-031 D1). Wrappers delegate;
   no parallel assembler. The lint rule prevents bypass paths.
2. **Single composite asyncpg query for Tier-1 chat** (ADR-031 D2).
   Tier-1 chat surface unchanged — Iota's composite query is the
   only memory-fetch path for `aiden_chat`. PM and Tier-2 wrappers
   reuse the same composite query.
3. **Canonical facts via tenant blob** (ADR-031 D3 + ADR-032 D-K2).
   Read-side unchanged. PM and Tier-2 surfaces consume the same
   `clients.canonical_facts_blob` (table-driven or folder-fallback
   per Kappa hybrid).
4. **2K token budget for Tier-1 chat, deterministic priority**
   (ADR-031 D4). Chat budget unchanged. PM/Tier-2 use 1.5K per
   D-L1; SOURCE_PRIORITY ordering from Kappa ADR-032 D-K3
   unchanged.
5. **Bundle lifetime = single HTTP request / single LLM call**
   (ADR-031 D5). Each memory_block is consumed by exactly one
   `invoke_tier_*` call. Chat-side bundle reuse on tool-call
   re-invoke (Iota AC #17) unchanged.
6. **Five-layer firewall** (ADR-031 §"Five-layer firewall"). Every
   wrapper invocation runs through Layers 1–5. Layer 4 validator
   rejects any scratch source against the sentinel
   operator — preserving per-operator isolation under the NULL
   submitter case.
7. **No global-top-k retrieval with post-filtering** (ADR-031
   §"Cache namespace isolation"). Every match remains
   tenant-scoped at query time.
8. **No new memory entry points** outside the central builder
   family. The wrappers are explicitly inside that family per
   §"Two wrappers" above.

## Consequences

### Pros

- Tier-1.5 PM and Tier-2 sub-agents now see canonical facts +
  workspace retrieval + path/folder/filename hits via the same
  validated builder path. The "I told Aiden the pricing — why is
  the deck wrong?" friction closes.
- Each surface is independently auditable via the
  `metadata->>'surface'` discriminator. Operators can group
  `memory.applied` rows by surface for cardinality + truncation
  analysis.
- Per-surface budgets (1.5K each for the new readers) keep total
  prompt size honest under the 50K WO ceiling. A 5-step workflow
  burns 9K of memory total — well under budget.
- Async dispatch (auto-routing + worker-driven step execution)
  inherits memory injection automatically via the wrapper calls in
  `routes/dispatch.py` and `workers/wo_dispatch_worker.py`.
- Operator identity falls back to the WO submitter for async paths
  (no session operator needed).
- The existing
  `tools/eslint-plugin-iwo3/rules/no-direct-llm-content-injection.ts`
  generalized cleanly — no new lint rule required.

### Cons / trade-offs

- The audit cardinality multiplier is real: 1 chat turn previously
  emitted 1 `memory.applied` row; a chat turn that triggers a
  5-step workflow now emits 1 + 1 + 5 = 7 rows (chat + PM + N
  Tier-2). At Klear's current volumes this is small; at GA scale
  the per-tenant audit-log size will track WO + step count.
- The sentinel UUID for NULL WO submitters silently skips scratch
  retrieval. Operators who submit a WO via legacy paths (no
  `submitted_by_user_id` recorded) will not see their personal
  scratch reach Tier-2. This is the safe default — alternative
  (tenant-wide scratch leak across operators) is forbidden by D-L4
  per-operator isolation.
- The deviation from D-L4's spec (assumed `created_by_user_id`,
  actual `submitted_by_user_id`) is bounded but worth noting in
  successor loops. NOT NULL enforcement is the natural follow-up.

### Carry-forwards

- **V3 — semantic / vector retrieval** (Loop Mu, opening next):
  add tenant-scoped vector index at write time, not global-then-
  filter. Architectural lock from ADR-031 §"Cache namespace
  isolation" extends.
- **NOT NULL enforcement on `submitted_by_user_id`**: deferred until
  a real operational need surfaces. The sentinel posture is safe
  for now.
- **Per-source-kind kill switches**: gated on operator demand.
- **AST-aware lint promotion**: per Iota D3 disposition; revisit
  only on a real bypass record.

## Verification

- 17 Lambda unit tests pass (`test_memory_lambda_unit.py`):
  per-surface budget invariants, Surface vocabulary, wrapper
  signatures, runtime kwarg threading, system-prompt prepending.
- 6 Lambda DB integration tests pass
  (`test_memory_lambda_wrappers_db.py`): PM wrapper + audit
  surface, Tier-2 wrapper + sub_agent_role, cross-tenant firewall,
  WO submitter resolution, sentinel fallback.
- Full pytest: 494 passed + 1 skipped + 1 flaky live-LLM (passes
  on retry — Tier-1 routing nondeterminism, not Lambda-related).
- CI cardinality gate: zero `memory.source_rejected` rows.
- Iota AC #1–#17 still green; Kappa AC #1–#12 still green
  (additive).
- vitest 588/588 against the Kappa baseline.

## See also

- `WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_LAMBDA_SCOPE_PROPOSAL_v0.1.0.md`
- `WS024_IWO3[Branch]/03_Orchestration/LOOP_LAMBDA_RECORD.md`
- ADR-031 (Memory V1 — binding predecessor for the chat surface)
- ADR-032 (Memory V1.5 — binding predecessor for path/filename/
  folder retrieval + canonical_facts hybrid)
- ADR-014 (RBAC + RLS — RLS canonical pattern preserved)
