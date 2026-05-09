# ADR-032 — Path-targeted retrieval + canonical facts CRUD table (Loop Kappa)

Date: 2026-05-08
Status: Accepted (Loop Kappa closeout).
**Relationship to ADR-031: extends, does not supersede.** ADR-031's
five-layer firewall + single-builder + 2K-budget locks remain
binding. ADR-032 only adds a parser → structured intent → assembler-
extension surface and a `canonical_facts` CRUD table; every ADR-031
guarantee is preserved verbatim and re-asserted explicitly in
§"Architectural locks honored" below. If ADR-031 says X about Memory
V1, ADR-032 says exactly the same X about Memory V1.5.
Predecessors: ADR-031 (Memory V1 deterministic retrieval — binding), ADR-014 (RBAC permission model + RLS posture).
Companions: `WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_KAPPA_SCOPE_PROPOSAL_v0.1.0.md`, `WS024_IWO3[Branch]/05_Artifacts/IWO3_MEMORY_PARITY_MATRIX_v0.1.0.md`.

## Context

Loop Iota shipped Memory V1 — a single central
`memory_context_builder` assembling four source kinds (canonical_facts,
chat_history, workspace_retrieval, scratch_retrieval) with a 2K token
budget and five-layer firewall. ADR-031 locked the architecture.

Five operator-visible parity gaps remained against IWO2's
`KnowHowService`:

1. Path-targeted retrieval — operators saying "from `04_Resources/Demo_Content`"
   got tsquery-only hits instead of folder-resolved files.
2. Filename retrieval — `artifacts.filename` was never searched directly.
3. Folder listing — no equivalent to `buildFolderListing()`.
4. Citation block — render output had per-source headers but no
   end-of-block citation index or grounding-rules preamble.
5. Canonical facts authoring — file-driven only via the `Canonical Facts/`
   workspace folder; no CRUD UI.

Plus operational completeness gaps inherited as Iota carry-forwards:

- `memory.source_rejected` had no operator surface and no CI cardinality
  assertion (M-009 carry-forward).
- M-002 (cleared-chat semantics) accepted as carry-forward by CODEX.
- D3 (heuristic-vs-AST lint) deferred per CODEX disposition.

## Decision

Ship Memory V1.5 as **assembler enrichment + canonical_facts CRUD
table + ops surface** — zero new memory readers; Tier-1 chat surface
only; ADR-031 architectural locks preserved verbatim.

### Path-targeted retrieval surface

A new `apps/api-fastapi/memory/intent_parser.py` ports IWO2's
`parseContextRequestFromChat()` into deterministic Python regex
extraction. Public function:

```python
def parse_context_intent(message: str) -> ContextIntent:
    """Returns paths[], filename_terms[], wants_folder_listing,
    wants_canonical_facts, keywords_remaining[]."""
```

Six phases (matching IWO2 minus code-block intent which is
**intentionally not ported** per parity matrix row 5):

1. Label-colon path extraction (`Web Style Guide: path/to/doc.md`).
2. Breadcrumb rewrite (`Workspace > 04_Resources > Foo` → slashed path).
3. Preposition + path (`from 04_Resources/Demo`).
4. Bare numbered folder (`04_Resources` → workspace folder).
5. Bare CapitalCase underscore-joined names (`Demo_Content`).
6. Quoted + extension-bearing filenames (`"foo.pptx"`, `bar.md`).

Plus two Kappa-new intent classes:

7. Folder listing intent (`what's in 04_Resources`, `list files in X`).
8. Canonical facts intent (`canonical facts`, `authoritative facts`,
   `what do we know about`).

The parser is pure: no DB, no I/O, no LLM.

### Assembler extension

`apps/api-fastapi/memory/assembler.py` accepts an optional
`intent: ContextIntent` parameter alongside the existing intake
string. The composite query gains two CTEs:

- `path_hits` — recursive walk of `workspace_folders` builds full
  paths; matches against the operator's `paths[]` either by full-path
  equality or by terminal-segment match. Score 1.0.
- `filename_hits` — `artifacts.filename ILIKE` against each operator
  filename term. Score 0.7.

When `intent.wants_folder_listing` is true and a path matches, an
optional follow-up query fetches structural directory data
(subfolders + files + counts) for the most specific matched path.
Synthesized as `MemorySource(kind="folder_listing", text=...)`.

Both new CTEs carry explicit `client_id = $1::uuid` predicates
and exclude operator-private folders (RLS Layer 3 belt + Layer 1 wall).

### Source priority + render polish

`SOURCE_PRIORITY` is reordered to give operator-explicit retrieval
intent the highest non-canonical priority:

| Priority | Kind | Truncation policy |
|---:|---|---|
| 1 | canonical_facts | Never dropped; char-truncated to fit if alone exceeds budget |
| 2 | path_targeted | Operator-explicit path intent |
| 3 | folder_listing | Synthesized directory map |
| 4 | filename_match | Operator-named filename |
| 5 | workspace_retrieval | tsquery hits |
| 6 | chat_history | Truncated from oldest first |
| 7 | scratch_retrieval | Dropped first |

`render_block()` adds two new sections:

- **`## GROUNDING RULES` preamble** — anti-hallucination posture;
  five lines instructing the LLM to use only the facts present in
  sources, not invent or extrapolate.
- **`## CITATIONS` index at end of block** — one line per kept source
  in the format `[<short_id>] <kind> — <filename or label> [score=…]`.

### Canonical facts CRUD table — D-K2 hybrid

A new `canonical_facts` table is the authoritative authoring source.
Schema:

```sql
CREATE TABLE canonical_facts (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id             uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    severity              text NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    version               integer NOT NULL DEFAULT 1,
    authored_by_user_id   uuid REFERENCES users(id) ON DELETE SET NULL,
    body                  text NOT NULL,
    is_active             boolean NOT NULL DEFAULT true,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE canonical_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE canonical_facts FORCE ROW LEVEL SECURITY;

CREATE POLICY canonical_facts_tenant_iso ON canonical_facts FOR ALL
    USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
    WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
```

Hybrid switch policy (D-K2):

- **Tenant has 0 active rows** → workspace-folder-driven blob path runs
  (Iota behavior preserved). The `Canonical Facts/` folder is the
  source.
- **Tenant has ≥1 active row** → table-driven blob rebuild on every
  mutation; folder path is skipped.

Switchover is automatic on the first INSERT. The
`clients.canonical_facts_blob` column from migration 0025 stays as
the denormalized read cache rebuilt by either path. Memory V1's
read side is unchanged.

`canonical_facts:set_severity` is a separate permission (owner +
admin only). Operators can update body and `is_active` but cannot
change severity — enforced inline in `routes/canonical_facts.py`
PATCH handler.

Soft-delete (`is_active=false`) preserves audit lineage.

### Hybrid switch implementation

`apps/api-fastapi/memory/canonical_facts.py` exposes:

- `refresh_canonical_facts_for_tenant(conn, client_id)` — original
  Iota folder-driven path (renamed: kept verbatim).
- `refresh_canonical_facts_from_table(conn, client_id)` — Kappa
  table-driven path (severity priority order: critical → high →
  medium → low, then version DESC, then created_at ASC).
- `refresh_canonical_facts_for_tenant_hybrid(conn, client_id)` — the
  switch: counts active table rows; calls table path if >0, folder
  path otherwise.

`routes/workspace.py` calls the hybrid version on every workspace
mutation; `routes/canonical_facts.py` CRUD handlers call the table
path directly.

### RBAC vocabulary expansion

Five new permission keys (87 → 92):

| Key | Owner | Admin | Operator | Reviewer | Viewer | Agent_System |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `canonical_facts:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `canonical_facts:create` | ✓ | ✓ | ✓ | — | — | — |
| `canonical_facts:update` | ✓ | ✓ | ✓ | — | — | — |
| `canonical_facts:delete` | ✓ | ✓ | — | — | — | — |
| `canonical_facts:set_severity` | ✓ | ✓ | — | — | — | — |

### Audit vocabulary expansion

Three new events under `LOOP_KAPPA_AUDIT_EVENTS` (138 → 141 events):

| Event | Trigger | Sample metadata |
|---|---|---|
| `canonical_facts.created` | POST /canonical_facts succeeds | `{fact_id, severity, version, body_length, blob_revision}` |
| `canonical_facts.updated` | PATCH /canonical_facts/{id} succeeds | `{fact_id, fields_changed[], previous_version, new_version, blob_revision}` |
| `canonical_facts.deleted` | DELETE /canonical_facts/{id} (soft) succeeds | `{fact_id, hard_delete: false, blob_revision}` |

The Loop Iota memory.* events are unchanged.

### Ops health surface

New Streamlit view at `apps/console-streamlit/views/ops_memory_health.py`
under the **Technical Console** sidebar group. Displays last-24h
buckets:

- `memory.applied` count.
- `memory.source_rejected` count + per-rejection detail (the M-009
  P0 firewall smoke alarm).
- `memory.bypassed` reason distribution.
- `memory.budget_truncated` per-kind frequency.

Read-only diagnostics; tenant-scoped via the audit log RLS.

### CI hard gate

New pytest `test_memory_source_rejected_ci_cardinality.py` asserts
the test DB has zero `memory.source_rejected` rows after the full
pytest pass. Failure indicates the firewall caught a regression —
treat as a P0 incident matching M-009's posture.

## Architectural locks honored

1. **One central memory builder** (ADR-031 D1). The parser feeds
   structured intent into the existing `memory_context_builder` —
   no parallel assembler.
2. **Single composite asyncpg query for Tier-1 chat** (ADR-031 D2).
   Two new CTEs added to the existing query; the optional
   folder-listing follow-up is the only second round-trip and it
   only fires when `wants_folder_listing` is true.
3. **Canonical facts via tenant blob** (ADR-031 D3). The table
   becomes the *authoring source*; the blob remains the
   *denormalized read cache*. Cache invalidation key
   `(client_id, "canonical_facts", revision)` unchanged.
4. **2K token budget, deterministic priority** (ADR-031 D4). Priority
   reordered to give path/folder/filename hits a higher slot than
   tsquery; canonical_facts still never dropped.
5. **Bundle lifetime = single HTTP request** (ADR-031 D5). Unchanged.
6. **Five-layer firewall** (ADR-031 §"Five-layer firewall"). New CTEs
   carry explicit `client_id = $1::uuid` predicates; new
   `canonical_facts` table has FORCE RLS; Layer 4 validator runs
   over every assembled source including the new kinds.
7. **No global-top-k retrieval with post-filtering** (ADR-031 §"Cache
   namespace isolation"). Every match is tenant-scoped at query time.
8. **No new memory entry points** outside the central builder family.
   The hybrid switch is a wrapper over the existing functions, not a
   parallel path.

## Consequences

### Pros

- Operators saying "from `04_Resources/Demo`" or "what's in `04_Resources`"
  now get path-resolved hits with score 1.0, not tsquery noise.
- Filename references ("the RMIS deck") match against
  `artifacts.filename`, no longer requiring extracted text to contain
  the filename tokens.
- `## GROUNDING RULES` preamble + `## CITATIONS` index in the
  rendered memory block give the LLM explicit anti-hallucination
  posture and a verifiable citation surface.
- Canonical Facts have a CRUD UI; operators are no longer forced to
  drop `.md` files into a workspace folder.
- The hybrid switch means tenants currently using the
  `Canonical Facts/` folder keep working without forced migration.
- `memory.source_rejected` has both an operator surface (Streamlit
  ops health view) and a CI cardinality assertion — M-009 is now
  observable end-to-end.
- All 17 Loop Iota acceptance criteria still green; 12 new Kappa
  acceptance criteria added.

### Cons / trade-offs

- The new path/filename/folder CTEs add SQL surface area to the
  composite query (+~100 lines of CTE). Acceptable: query plan still
  uses the existing GIN index for tsquery; new CTEs hit the
  `workspace_folders` RLS-scoped indexes; per-turn cost stays under
  the ADR-031 30ms 95p envelope.
- The folder-listing follow-up query is a second DB round-trip when
  intent matches. Bounded: fires only when `wants_folder_listing`
  is true, which is a small fraction of turns.
- The `canonical_facts` table adds another tenant-scoped surface
  with FORCE RLS. Five lint rule asserts this; `migration_source_manifest`
  registration confirms.
- The hybrid switch logic adds a count query before each refresh.
  Cheap (single-row aggregate on a tenant-scoped index).
- `canonical_facts:set_severity` adds a sixth distinct
  canonical_facts permission key. The route handler does an inline
  permission check using the existing decider — no new dep type.

### Carry-forwards (unchanged from ADR-031)

- **V2 — Tier-2 sub-agent memory injection.** Lambda. Per-surface
  budget allocation (PM=1.5K, Tier-2=1.5K) + `surface` discriminator
  on `memory.applied` + `work_orders.created_by_user_id` NOT NULL
  for async operator scope.
- **V3 — Vector / semantic recall.** Trigger conditions in ADR-031.
- **AST-aware lint promotion.** Iota D3 disposition kept; revisit
  only on a real bypass record.
- **Per-source-kind kill switches.** Gated on operator demand.

## Verification

- Migration 0026 applies cleanly on local + tenant-scoped policies
  enforced.
- Manifest populated with 42 tables (was 41); zero drift.
- 32 Kappa unit tests pass (`test_memory_kappa_unit.py`): parser
  regex coverage, render_block sections, SOURCE_PRIORITY invariants,
  budget allocation under new ordering.
- 5 Kappa DB integration tests pass (`test_memory_kappa_paths_db.py`):
  path_hits resolves named folder, cross-tenant isolation, filename
  hits, folder_listing structural fetch, end-to-end render.
- 8 canonical_facts route tests pass (`test_canonical_facts_route.py`):
  CRUD round-trip, severity-permission gate (operator 403,
  owner 200), invalid severity 400, cross-tenant 404, blob rebuild
  reaches memory builder, audit emission for create/update/delete.
- 1 CI cardinality gate test passes (`test_memory_source_rejected_ci_cardinality.py`):
  zero rejections on the test DB after the full pytest pass.
- Streamlit smoke 25 views including `canonical_facts.py` and
  `ops_memory_health.py`.
- Full pytest: 472 passed, 1 skipped (no regressions vs Iota
  baseline `iwo3/main @ 12a151b`).

## See also

- `WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_KAPPA_SCOPE_PROPOSAL_v0.1.0.md`
- `WS024_IWO3[Branch]/05_Artifacts/IWO3_MEMORY_PARITY_MATRIX_v0.1.0.md`
- `WS024_IWO3[Branch]/03_Orchestration/LOOP_KAPPA_RECORD.md`
- ADR-031 (Memory V1 — binding predecessor)
- ADR-014 (RBAC + RLS — RLS canonical pattern)
