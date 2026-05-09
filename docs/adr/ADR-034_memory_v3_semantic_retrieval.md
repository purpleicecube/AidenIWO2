# ADR-034 — Memory V3 semantic retrieval (Loop Mu)

Date: 2026-05-09
Status: Accepted (Loop Mu closeout — Chroma-only first; KG augmentation deferred).
**Relationship to ADR-031 / 032 / 033: extends, does not supersede.**
ADR-031's five-layer firewall + single-builder + 2K-budget locks remain
binding. ADR-032's parser → assembler-extension surface +
canonical_facts hybrid remain binding. ADR-033's wrapper family +
per-surface budgets + audit `surface` discriminator remain binding.
ADR-034 only adds a **fifth retrieval source kind** (`semantic_retrieval`)
+ a tenant-scoped vector store + an opt-in indexing path. Every
guarantee from ADR-031/-032/-033 is preserved verbatim — re-asserted
explicitly in §"Architectural locks honored" below.

Predecessors: ADR-031, ADR-032, ADR-033. Companions:
`WS024_IWO3[Branch]/03_Orchestration/LOOP_MU_RECORD.md`,
`WS021_KlearMarketing/06_KlearOpen/klearopen-app/kg_engine.py` (DigiFLOW pattern reference).

## Context

Loop Iota shipped Memory V1 — Tier-1 chat memory, deterministic
retrieval (path > filename > tsquery). Loop Kappa shipped V1.5 —
operational maturity for the chat surface. Loop Lambda shipped V2 —
runtime breadth (PM, Tier-2, WO/WF) via wrappers.

The remaining gap: deterministic keyword retrieval misses operator
queries that don't share vocabulary with the indexed text. "Tell me
about pricing for the enterprise plan" never matches a deck titled
`klear_revenue_model_2026.pptx` even when the deck is exactly the
right grounding artifact. Memory V3's job is to add **fuzzy
semantic retrieval** as a supplemental capability, **without**
replacing deterministic-first posture.

The brief authorized: "inspect DigiFLOW first; reuse simplest sane
pattern; preferred Chroma + lightweight KG; fall back to
Chroma-only if KG would jeopardize bounded completion."

DigiFLOW's `kg_engine.py` runs ChromaDB PersistentClient with
per-KG collections (`kg_<kg_id>`), 500-token chunks with 50-token
overlap, cosine similarity space, default embedding
(all-MiniLM-L6-v2 via Chroma's bundled `DefaultEmbeddingFunction`).
DigiFLOW's KG layer is a **separate** LangChain
LLMGraphTransformer → JSON storage subsystem; vector and KG are
parallel grounding lanes, not coupled. IWO3 has no equivalent of
the LLM-graph-extraction pipeline; its structured layer is
`canonical_facts` table + `workspace_folders` tree.

## Decision

**Ship Chroma-only first.** Defer KG augmentation. The DigiFLOW KG
layer is its own multi-month project (LangChain LLMGraphTransformer,
NetworkX adapter, KG insights service, registry, visualization);
porting it to IWO3 in this loop would jeopardize bounded completion
of the V3 minimum acceptable outcome.

What ships in Loop Mu:

1. `apps/api-fastapi/memory/vector_store.py` — wraps ChromaDB
   PersistentClient with per-tenant collections.
2. `semantic_retrieval` source kind in `MemorySourceKind`; slot 6
   in `SOURCE_PRIORITY` (between `workspace_retrieval` tsquery and
   `chat_history`).
3. Best-effort indexing on workspace file create.
4. Cross-tenant isolation at index time (per-tenant collection +
   metadata `client_id` defensive belt).
5. Env-level kill switch `IWO3_SEMANTIC_RETRIEVAL_ENABLED` (default
   ON).

What is **deferred**:

- KG augmentation. Documented in §"Successor candidates" + flagged
  as the natural V3.5/V4 follow-up.
- Per-tenant `clients.semantic_retrieval_enabled` flag. Today's
  per-tenant kill switch is `clients.memory_enabled` (Iota); when
  semantic noise becomes an operator-reported issue, add the
  granular flag.
- Backfill / re-index endpoint. Today's indexing is best-effort on
  workspace write. Operator-driven backfill is a follow-up if
  retroactive indexing of existing artifacts becomes needed.
- Semantic retrieval for non-chat surfaces (PM, Tier-2). The
  Lambda wrappers already inherit semantic via the central
  `memory_context_builder` (the assembler runs the same query for
  all surfaces). No additional wiring needed.

### Per-tenant collection naming

`tenant_<client_id>` is the index-time tenancy boundary. A Chroma
query against `tenant_A` cannot return `tenant_B` chunks because
they live in separate collections. **This is the V3 firewall
constraint locked in ADR-031 §"Cache namespace isolation": no
global-then-filter retrieval.** Each chunk's metadata also carries
`client_id`; `vector_store.semantic_search_for_tenant` validates
the metadata field defensively as a safety belt.

### Chunking

DigiFLOW-parity: 500-token chunks (~2000 chars) with 50-token
overlap (~200 chars). Token approximation: 1 token ≈ 4 chars.
Tested on synthetic 5000-char texts → produces 3 chunks with
proper overlap.

### Source priority slot 6 (D-M1)

```
canonical_facts (1) → path_targeted (2) → folder_listing (3) →
filename_match (4) → workspace_retrieval (5, tsquery) →
semantic_retrieval (6, vector cosine) → chat_history (7) →
scratch_retrieval (8)
```

Rationale: deterministic operator-explicit signals (path / folder /
filename) outrank tsquery (exact keyword match), which outranks
fuzzy semantic. Semantic outranks chat_history for the same reason
tsquery does in Kappa: when retrieval signal is present, grounding
beats continuity. Scratch is still last to drop. Canonical facts
are still first and never dropped.

### Indexing trigger

Best-effort sync on workspace file create. The `POST
/workspace/files` route, after `INSERT INTO artifacts` and the
canonical_facts hook, calls `index_artifact_for_tenant` with the
extracted_text. Failure is silently swallowed at the route layer —
indexing never blocks workspace UX. Binary content
(`b64:` prefix) is skipped (no useful embedding signal).

PATCH and DELETE paths intentionally do NOT delete or re-embed
on rename/move (the chunk's chunked text is unchanged) and the
soft-delete on the artifact preserves the chunks (the artifact is
hidden from workspace API but the embedding still scores against
the text). **Hard-delete + chunk cleanup is a follow-up** per
§"Successor candidates".

### Top-N + scoring

`SEMANTIC_RETRIEVAL_TOP_N = 3` (smaller than `RETRIEVAL_TOP_N = 3`
for tsquery — equivalent for now, but the constant is independent
in case noise tuning requires a smaller top-K later). Score is
cosine similarity (`1.0 - distance`), in `[0, 1]`. Threshold is
NOT applied in the assembler — every returned chunk lands in the
bundle and the budget allocator decides truncation. This matches
DigiFLOW's posture: noisy chunks lose to budget pressure rather
than a hard score gate.

### Storage location

`/home/virgina/VS_AIDEN_IWO3/.local/chroma/` (resolved relative to
the repo root via `Path(__file__).resolve().parents[2]`). Mirrors
the `.local/skills/` convention from MegaLoop Theta.

**Hosted rollout (deferred):** Railway containers have ephemeral
local disk by default. Hosting needs either a Railway persistent
volume mounted at `.local/chroma/` OR migrating to ChromaDB's
HTTP server mode + a separate Chroma service. **This loop does
not solve hosted persistence** — local-only first; documented in
the Loop Mu record's deviations list. The env kill switch
(`IWO3_SEMANTIC_RETRIEVAL_ENABLED=false` on hosted) cleanly
disables semantic on the hosted environment until the persistent-
volume work is done.

## Architectural locks honored

1. **One central memory builder** (ADR-031 D1). Semantic retrieval
   results land in `MemorySource(kind="semantic_retrieval", ...)`
   inside the same `assemble_sources` function. No parallel
   assembler. Lambda wrappers inherit semantic automatically — they
   delegate to `memory_context_builder` which now includes the
   semantic source kind.
2. **Single composite asyncpg query for SQL paths** (ADR-031 D2).
   The Chroma query is OUTSIDE the composite SQL because Chroma
   has its own runtime; it's an explicit second round-trip,
   gated on env + intake length, capped at top-K=3 and ~5–10ms
   median latency.
3. **Tenant-scoped at index time, not query time** (ADR-031
   §"Cache namespace isolation"). Per-tenant collection naming +
   metadata `client_id` defensive belt. Cross-tenant integration
   test asserts (`test_cross_tenant_index_isolation`).
4. **Bundle lifetime = single LLM call** (ADR-031 D5). Semantic
   results are part of the bundle returned by
   `memory_context_builder`; bundle reuse posture from Iota / Kappa
   / Lambda unchanged.
5. **Five-layer firewall** (ADR-031 §"Five-layer firewall"). Layer
   1 (data-model scoping) preserved — every chunk carries
   `client_id` metadata. Layer 2 (tenant-scoped FastAPI conn)
   irrelevant to Chroma path but the SQL paths in the composite
   query are still tenant-scoped. Layer 3 (explicit `client_id =
   $1` predicates) preserved — and Chroma adds an analogous
   predicate via the per-tenant collection lookup. Layer 4
   (assembly-time validation) preserved — the validator runs over
   every assembled source including `semantic_retrieval`. Layer 5
   (cache namespace isolation) preserved — Chroma collections are
   the namespace.
6. **No global-top-k retrieval with post-filtering**. Per-tenant
   collection means top-K is computed AGAINST a single-tenant
   index — never a global index post-filtered.
7. **No new memory entry points** outside the central builder
   family. The vector store is a service called BY
   `assembler.fetch_memory_inputs`; it does not provide an LLM
   call or a memory-string assembly path of its own.

## Consequences

### Pros

- Operators get fuzzy retrieval grounding for natural-language
  queries that don't share vocabulary with indexed text. The "tell
  me about pricing" → "klear_revenue_model.pptx" use case closes.
- Lambda's PM + Tier-2 wrappers inherit semantic retrieval
  automatically — no additional wiring needed at those surfaces.
- Indexing happens on artifact creation; no operator action
  required for new content. Backfill of existing artifacts is a
  separate follow-up if needed.
- Tenant-scoped collections satisfy the V3 firewall constraint
  cleanly — there is no global index that could be misqueried.
- The env kill switch + tenant `memory_enabled` flag give two
  layers of bypass for environments where Chroma is unavailable
  or disabled.
- ChromaDB's bundled embedding model (all-MiniLM-L6-v2) requires
  no external API key; the model downloads on first use (~22MB).

### Cons / trade-offs

- **Hosted persistence is unsolved in this loop.** Railway needs
  either a persistent volume or HTTP-mode Chroma. Documented
  deferred. Local-dev works fine; hosted needs operator follow-up.
- ChromaDB adds ~30 transitive dependencies (sentence-transformers,
  tokenizers, onnxruntime, posthog, etc.). The bundle is shipped
  in the IWO3 venv but not on hosted Railway until the persistence
  work is done.
- First semantic search after a fresh process boot pays a model-
  load cost (~1–2 seconds) for the embedding model. Subsequent
  queries are fast. Acceptable for a chat surface; might surface
  on cold-start cardinality if hosted Railway containers cycle
  often.
- KG augmentation deferred — IWO3 does not yet have an LLM-driven
  graph-extraction pipeline. When it lands, semantic retrieval can
  be augmented with KG-derived edges; today, semantic stands alone.
- No score threshold gate — noisy chunks land in the bundle and
  get budget-truncated. If operators report semantic noise, add
  a per-tenant minimum-score gate as a follow-up.

### Carry-forwards

- **KG augmentation (V3.5 candidate)** — port DigiFLOW's
  `kg_engine.py` LangChain LLMGraphTransformer pattern into IWO3
  if operators report retrieval misses that semantic alone doesn't
  fix (e.g., entity-relationship questions like "which deals did
  Pete close in Q1"). Trigger condition: real operator demand,
  not theoretical fit.
- **Hosted Chroma persistence**: Railway persistent volume OR
  HTTP-mode Chroma service. Operator follow-up.
- **Hard-delete + chunk cleanup hook**: when an artifact is hard-
  deleted, remove its chunks via `remove_artifact_from_tenant`.
  Currently soft-delete preserves chunks (acceptable for V3
  minimum).
- **Per-tenant `semantic_retrieval_enabled`** column on `clients`:
  add when granular kill switch becomes operationally needed.
- **Score threshold gate**: when semantic noise becomes an issue,
  add a tunable minimum cosine score below which results are
  dropped before assembly.
- **Re-index endpoint**: `POST /memory/semantic_retrieval/reindex`
  for backfilling existing artifacts. Add when operator demand
  surfaces.

## Verification

- 20 V3 unit tests pass (`test_memory_mu_unit.py`): chunking math,
  env kill switch, collection naming, SOURCE_PRIORITY new ordering,
  render_block semantic section, budget allocator behavior with
  semantic_retrieval kind.
- 5 V3 Chroma integration tests pass (`test_memory_mu_chroma_db.py`):
  index → search round-trip; cross-tenant index isolation
  (firewall); end-to-end via `memory_context_builder` (semantic
  section reaches `bundle.block`); collection deletion; env kill
  switch end-to-end.
- Full pytest: 520 passed + 1 skipped (was 494/1 at Lambda; +25 Mu;
  0 regressions).
- CI cardinality gate: zero `memory.source_rejected` rows.
- Iota AC + Kappa AC + Lambda AC all still green.

## See also

- `WS024_IWO3[Branch]/03_Orchestration/LOOP_MU_RECORD.md`
- `WS021_KlearMarketing/06_KlearOpen/klearopen-app/kg_engine.py` (DigiFLOW reference pattern)
- ADR-031 (Memory V1 — binding architectural floor)
- ADR-032 (Memory V1.5 — Kappa chat surface)
- ADR-033 (Memory V2 — Lambda runtime breadth)
- ADR-014 (RBAC + RLS — tenancy substrate)
