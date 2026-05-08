# ADR-031 — Memory V1 deterministic retrieval (Loop Iota)

Date: 2026-05-08
Status: Accepted (Loop Iota closeout).
Predecessors: ADR-029 (Beta-1 production posture — RLS + chat_sessions + per-tenant ceilings), ADR-021 (LLM runtime), ADR-014 (RBAC permission model + RLS posture).
Companions: `IWO3_LOOP_IOTA_SCOPE_PROPOSAL_v0.1.0.md`, `IWO3_LOOP_IOTA_TENANT_FIREWALL_PACKAGE_v0.1.0.md`, `IWO3_LOOP_IOTA_PERFORMANCE_BUDGET_NOTE_v0.1.0.md`.

## Context

Pre-Iota IWO3 chat was amnesic at the LLM boundary. `aiden_chat`
passed only the current message to `invoke_aiden_tier_1`. `chat_sessions`
persisted operator history for UI hydration but was never injected into
LLM calls. There was no Python equivalent of IWO2's `KnowHowService`,
no canonical-facts grounding, no operator-scratch retrieval, and no
vector store. `work_orders.gcc_memory` carried per-WO breadcrumbs but
was not a cross-feature learning layer.

CODEX delivered a five-layer Tenant Memory Firewall position
(client_id scoping + RLS + tenant-scoped FastAPI connections +
assembly-time validation + cache namespace isolation) and framed the
work as a **retrofit, not a rebuild**: IWO3 already has the right
tenancy foundation; what's missing is a central memory assembly path.

The performance audit showed a naive plan would amplify per-turn
non-LLM overhead 3–5× from a ~10–15ms baseline. P0 optimizations
brought the median add to ~5–10ms.

## Decision

Ship Memory V1 as a single central builder
(`memory_context_builder(conn, client_id, user_id, message)`) that
assembles four kinds of memory in a deterministic order, validates
every source against the active tenant + operator, allocates under a
2,000-token hard budget, and returns a renderable block ready to
inject into the Tier-1 user payload.

### Architecture

```
                 POST /aiden/chat (tenant-scoped FastAPI conn)
                              │
                              ▼
                  memory_context_builder()
                              │
                  ┌───────────┴───────────┐
                  │   single composite    │
                  │   asyncpg query       │
                  │   (CTE-based,         │
                  │   client_id = $1      │
                  │   everywhere)         │
                  └───────────┬───────────┘
                              │
                  ┌───────────┴───────────┐
                  │  4 source kinds:      │
                  │   canonical_facts     │
                  │   chat_history        │
                  │   workspace_retrieval │
                  │   scratch_retrieval   │
                  └───────────┬───────────┘
                              │
                  ┌───────────┴───────────┐
                  │  validate_tenant_     │
                  │  safety()             │
                  │  (firewall Layer 4)   │
                  └───────────┬───────────┘
                              │
                  ┌───────────┴───────────┐
                  │  budget allocator     │
                  │  (2K tokens, priority │
                  │  truncation)          │
                  └───────────┬───────────┘
                              │
                  ┌───────────┴───────────┐
                  │  audit:               │
                  │   memory.applied      │
                  │   (or .bypassed)      │
                  │   (and .truncated)    │
                  │   (and .rejected)     │
                  └───────────┬───────────┘
                              │
                              ▼
              invoke_aiden_tier_1(memory_block=..., ...)
```

### Schema (migration 0025)

`clients` gains three columns:

- `memory_enabled BOOLEAN NOT NULL DEFAULT true` — per-tenant kill switch.
- `canonical_facts_blob TEXT` — denormalized concatenation of `Canonical Facts/*.md` files in the tenant workspace.
- `canonical_facts_revision INT NOT NULL DEFAULT 0` — monotonic counter; cache key for the in-process LRU.

`artifacts` gains:

- `extracted_text_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(extracted_text, ''))) STORED` — tenant-scoped GIN-indexed full-text retrieval column.
- `artifacts_extracted_text_gin` GIN index for `@@ plainto_tsquery(...)` queries.

No new tables. The retrofit reuses the existing `chat_sessions`,
`artifacts`, and `workspace_folders` surfaces (each already
tenant-owned with `client_id`, RLS-FORCE'd, and accessed via the
`get_tenant_scoped_connection` FastAPI dep).

The `artifacts.extracted_text_tsv` GENERATED column is an
**intentional managed drift / raw-SQL-owned surface**: Drizzle's
pg-core does not declaratively model GENERATED ALWAYS tsvector +
STORED, so this column is owned by the migration and referenced by
runtime code only via raw SQL in `apps/api-fastapi/memory/assembler.py`.
This matches the partition-by-range posture used for `action_audit_log`
in Loop 2.1.5 — same architectural exception, same documented trade-off.

### Five-layer firewall (CODEX position)

1. **Data-model scoping** — every memory-bearing source carries
   `client_id`. `clients.canonical_facts_blob` lives on the tenants
   row itself; chat_sessions has `(user_id, client_id)`; artifacts +
   workspace_folders carry `client_id` and `owner_user_id` (where
   relevant).
2. **Connection-level enforcement** — `memory_context_builder` accepts
   a tenant-scoped connection from the caller. No new raw DB clients.
   `SET LOCAL ROLE iwo3_app + app.current_client_id` is the FastAPI
   dep posture.
3. **Query-level enforcement** — every CTE in the composite assembler
   carries explicit `client_id = $1` predicates. RLS is the hard wall;
   the predicates are the safety belt (per ADR-014 §Q4 keep_both
   posture).
4. **Assembly-time validation** — `validate_tenant_safety` walks every
   assembled source before the bundle is injected. Mismatches are
   dropped, audited as `memory.source_rejected`, and the bundle
   continues with surviving sources. **In normal operation this audit
   row should never fire** — it is the firewall's smoke alarm
   (M-009 in the loop risk register; ops runbook treats any non-zero
   count as P0).
5. **Cache namespace isolation** — the in-process canonical facts cache
   is keyed on `(client_id, "canonical_facts", revision)`. The scratch
   terms cache (60s TTL) is keyed on
   `(client_id, user_id, "scratch", terms_hash)`. **Bundles themselves
   are never cached across requests.** A future vector store (V2+) must
   be tenant-scoped at *index time*, not query time — never global
   top-k then filter after.

### Memory budget (2,000 tokens, priority truncation)

| Priority | Kind                | Truncation policy |
|---:|---|---|
| 1  | canonical_facts     | Never dropped; if alone exceeds budget, char-truncated to fit |
| 2  | chat_history        | Truncated from oldest first |
| 3  | workspace_retrieval | Lowest-score entries dropped first |
| 4  | scratch_retrieval   | Dropped first when over-budget |

Truncation events emit `memory.budget_truncated` audit. The 2K cap
leaves >40K tokens for the rest of the Tier-1 prompt + completion
under the 50K WO ceiling locked in Beta-1 ε.1 (ADR-029 §Q1).

### Bundle lifetime = single HTTP request

Memory bundles are assembled per HTTP request and reused only within
that request — specifically the tool-call re-invoke path at
`apps/api-fastapi/routes/aiden.py:412` carries the SAME bundle into
the second `invoke_aiden_tier_1` so exactly one `memory.applied`
audit row fires per chat HTTP request (acceptance criterion §AC #17).

### Canonical facts via tenant blob, not file scan

The `Canonical Facts/` workspace folder is the operator-facing source
of authoritative facts. A workspace-write hook
(`memory.canonical_facts.refresh_canonical_facts_for_tenant`)
recomputes the blob on any file or folder mutation and bumps
`canonical_facts_revision`. Chat turns read the blob from the
`clients` row in the same composite query that fetches every other
source — zero per-turn folder enumeration cost.

The hook is wrapped in `async with conn.transaction()` savepoints so
a refresh failure (e.g. malformed extracted_text) cannot poison the
caller's transaction.

### Deterministic retrieval — no embeddings in V1

Workspace + scratch retrieval uses `plainto_tsquery('english', $)`
against the `extracted_text_tsv` GIN index. Top-3 results per kind.
Scoring via `ts_rank_cd`. No embeddings, no semantic similarity, no
external vector DB.

The scratch intent classifier is a regex (`\bmy\s+(scratch|notes?|drafts?|memos?|files?|workspace)\b`) — no second LLM call, no token cost.

## Consequences

### Pros

- Aiden remembers the last 6–10 chat turns within an operator's
  session.
- Workspace files ground answers deterministically (operators can
  reference "find my deck on RMIS" and the assembler picks the
  matching artifact).
- Canonical facts override hallucinations within one chat turn after
  the operator drops a fact file in `Canonical Facts/`.
- Operator scratch becomes retrievable and operator-private — same
  tenant, different operator gets a different bundle.
- Every memory source is provably tenant-safe (RLS + explicit
  predicates + assembly-time validation) and auditable (`memory.applied`
  carries `sources_used[]` with record IDs).
- The `no-direct-llm-content-injection` lint rule prevents future
  bypass paths from creeping in.

### Cons / trade-offs

- The `artifacts.extracted_text_tsv` GENERATED column adds real cost on
  every artifact INSERT/UPDATE (Postgres recomputes the tsvector). For
  typical extractions (~10–50KB) this is sub-ms; for large extractions
  (>500KB) it can hit 5–20ms. Acceptable because artifact writes are
  not on the chat hot path. **Future loops with very large extractions
  may need to revisit.**
- **Migration 0025 builds the GIN index in-transaction.** Acceptable at
  current artifact volumes (Klear=16 rows, FFAI=0). **Threshold for
  switching future GIN-touching migrations to `CREATE INDEX
  CONCURRENTLY` (operator-driven, outside the migration tx):** any
  tenant's `artifacts` row count crosses **5,000 rows** OR the in-tx
  migration apply duration on hosted exceeds **10 seconds**. Today's
  volumes are 300x under threshold; revisit at the watermark.
- **The `no-direct-llm-content-injection` lint rule is a heuristic
  guardrail, not an AST-proof security boundary.** The rule scans
  Python source for the kwarg pattern `memory_block=...` and asserts
  either an `import from memory` statement is present in the same file
  or the file is allowlisted (`memory/` package, `routes/aiden.py`,
  `tests/`). This catches accidental bypass paths and signals
  reviewer intent — sufficient for V1 — but a determined contributor
  could still construct a literal call that passes the heuristic
  (e.g. by importing a memory symbol the rule doesn't actually use).
  Promotion to AST-aware analysis is a successor candidate (V1.x) only
  if a real bypass attempt is recorded; otherwise the heuristic is
  the right cost/benefit point for V1.
- The workspace-write hook recomputes the canonical facts blob on
  every file/folder mutation, even when the mutation is unrelated to
  `Canonical Facts/`. The cost is small (recursive CTE returns 0 rows
  when no `Canonical Facts/` folder exists) but non-zero. **Revisit if
  workspace write throughput becomes a concern.**
- No tier-2 sub-agent memory injection in V1. Token cost is compounding
  on multi-step WOs; deferred to V2.
- No vector / semantic recall in V1. Deterministic keyword + path
  retrieval is sufficient at alpha-pilot artifact volumes (≤1000
  artifacts per tenant). V2 will add tenant-scoped embeddings.
- Per-tenant `memory_enabled=false` is a coarse kill switch; there is
  no per-source-kind disable yet.

### Carry-forwards

- **V2 tier-2 injection** — when token budget allows, port the same
  builder pattern to `invoke_pm_tier_1_5` and `invoke_sub_agent_tier_2`.
- **V2 vector store** — pgvector or per-tenant chroma collections,
  tenant-scoped at index time. Lock the no-global-top-k rule in the
  successor ADR.
- **V1.5 canonical facts CRUD UI** — once the file-driven path is
  proven, layer a dedicated `canonical_facts` table with severity /
  version / authored_by and a Streamlit CRUD surface.
- **GCC cross-feature learning rebuild** — separate effort; gated on
  actual operator demand.

## Verification

- Migration 0025 applied cleanly on local + hosted Railway Postgres.
- 24 memory unit tests (budget, validator, cache, intent regex) pass.
- 6 firewall integration tests pass — cross-tenant chat, cross-tenant
  artifacts, cache namespace isolation, validation rejection, env
  kill switch, per-tenant kill switch.
- 2 chat-route integration tests pass — `memory.applied` writes once
  per request, response carries `memory_sources` for Streamlit chips.
- 7 lint rule tests pass — `no-direct-llm-content-injection` flags
  ad-hoc injection, allows the central builder, allowlists the memory
  package + tests + the `aiden.py` route.
- Full pytest: 426 passed, 1 skipped (no regressions vs. pre-Iota
  HEAD `d219bbd`).
- Vitest: 554 passed in the non-stale-state subset (pre-existing 8
  failures in tenant-isolation tests stem from operator-exercise DB
  drift, unchanged from Loop Eta CLAUDE.md note).
- npm check + tsc: clean.

## See also

- `WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_IOTA_SCOPE_PROPOSAL_v0.1.0.md`
- `WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_IOTA_TENANT_FIREWALL_PACKAGE_v0.1.0.md`
- `WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_IOTA_PERFORMANCE_BUDGET_NOTE_v0.1.0.md`
