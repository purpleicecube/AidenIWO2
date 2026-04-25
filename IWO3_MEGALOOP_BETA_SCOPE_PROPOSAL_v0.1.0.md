# IWO3 MegaLoop Beta — Scope Proposal v0.1.0

Date: 2026-04-25
Status: Draft for CODEX review.
Predecessors: `MEGALOOP_ALPHA_RECORD_v0.1.0.md`, `IWO3_ALPHA_CLOSEOUT_GAP_PUSH_RECORD_v0.1.0.md`, `IWO3_PRE_BETA_PRODUCT_SURFACE_REMEDIATION_LOOP_RECORD_v0.1.0.md`.
Companions (this package): `IWO3_MEGALOOP_BETA_PRESTART_QUESTIONS_v0.1.0.md`, `MEGALOOP_BETA_COVERAGE_MAP_v0.1.0.md`, `IWO3_MEGALOOP_BETA_RISK_ALIGNMENT_NOTE_v0.1.0.md`.

## A. Beta purpose

**Alpha proved the runtime. Pre-Beta (β + γ + δ) proved operator-trust UX and product surface. Beta proves IWO3 is production-grade and capability-broad enough for an outside pilot tenant.**

What Alpha proved (recap):
- Three-tier LLM stack (Aiden / PM / Tier 2) on real providers (Groq + OpenRouter)
- Channel layer + Telegram operator surface
- Browser console with 12+ live pages
- Gamma live render with dual-gate + async polling
- RBAC + RLS + audit log foundation

What Pre-Beta proved:
- LLM config CRUD + sub-agent metadata model (β)
- End-to-end runtime path browser-reachable (β)
- Telegram operational not theoretical (β)
- Operator-trust path complete (γ): chat → run → output discovery
- Aiden persona is IWO2-faithful (δ.5)
- Workspace is real: nested folders, file CRUD, auto-saved outputs (δ)

**What Beta must prove that Alpha and Pre-Beta did not:**

1. **IWO3 is safe for an external pilot tenant.** Production auth, credential posture, observable health surfaces.
2. **IWO3 is more than one channel + one external adapter.** Slack adapter + Sandbox PPTX/PDF live, both reusing the Alpha foundations.
3. **IWO3 has durable operator state.** Cross-session chat context, server-side WO idempotency, workspace file content fetch, hard-delete semantics.
4. **IWO3's Aiden is a sustained product, not a single-turn classifier.** Persona library, conversational maturity, capability awareness.
5. **IWO3 has a coherent answer to tool/MCP integration** — at minimum a registry shape, even if richer execution lands post-Beta.

Beta is **not** a redesign loop. It is a maturity loop on top of the Alpha + Pre-Beta foundations. No closed Alpha work reopens unless a Beta dependency forces it.

## B. Original roadmap mapping

The IWO3 architecture sequence (`WS024_IWO3[Branch]/CLAUDE.md` § Architecture Sequence) listed 15 areas; Beta primarily consumes:

| Roadmap area | Loop coverage | Beta status |
|---|---|---|
| 12. Unified artifact delivery: Gamma/local PPTX/PDF for single-WO and workflow paths | Loop 9 (Gamma live) | **Beta — Sandbox PPTX/PDF expansion** |
| 14. Operator diagnosis: stuck-WO diagnosis service, API, and UI | partial via γ.4 | **Beta — diagnosis service + UI** |
| 15. Slack adapter using the same channel layer | foundation in α.5/α.6 | **Beta — Slack live** |
| Production-hardening (not numbered; Stage A § F1) | dev-bearer in Alpha | **Beta — production auth + encrypted creds** |
| MCP servers + tool integration | architecture mentioned, not built | **Beta — tool registry v1 (shape, not full execution)** |

What stays out of Beta scope (deferred to GA / Loop 12+):
- Cross-channel identity merging
- Multi-region production deployment
- Streaming LLM responses (still Beta-deferred per ADR-024)
- Cost-aware provider arbitration **at runtime** (registry shape may land in Beta)
- Aiden conversation-memory durability beyond per-session

## C. Scope buckets

### Beta MUST-HAVE

These items must ship and be live-verified before Beta closes.

| Item | Theme | Origin question | Acceptance |
|---|---|---|---|
| Production auth (signed JWT or external) | Production-hardening | Q2 (Beta auth choice) | Dev bearer disabled in production env; signed token round-trip; sessions expire |
| Encrypted-at-rest credential posture | Production-hardening | ADR-024 deferred list | Provider keys stored encrypted at rest; runtime decryption only; rotation path |
| Channel webhook endpoint design (Telegram + Slack ready) | Channel | Q3 (webhook endpoint shape) | `/webhook/<channel>` accepts signed inbound; long-poll worker remains as fallback |
| Slack adapter (live, ChannelAdapter implementation) | Capability — channels | theme #3 | Two channel kinds working concurrently; Slack /start binding + intent dispatch end-to-end |
| Sandbox PPTX/PDF live adapter | Capability — outputs | theme #2 | Parity with Gamma's dual-gate + async polling; sandbox WO produces artifact |
| Server-side WO idempotency for chat-driven creates | Operator trust | Q8 | UNIQUE constraint on `(client_id, correlation_id)` for chat-* correlations; client-side guard becomes belt-and-suspenders |
| Cross-session chat context durability | Operator trust | Q7 | Chat history per (operator, tenant) persists in DB; "where is the output?" works after a refresh |
| Workspace file content fetch route | Workspace | δ Q9 | `GET /workspace/files/{id}/content` returns text or binary; UI renders txt/md/json/csv inline |
| Workspace hard-delete model | Workspace | δ Q10 | Admin-explicit hard delete on folders + files; soft-delete remains default |
| `/health/channels` + `/health/llm` | Observability | open from γ R-024 | Browser surface shows token resolution status; channel worker liveness exposed |
| Tool/MCP registry v1 shape | Capability — tools | theme #6 | New `tool_definitions` table + read-only browser surface; per-agent ACL stub; no live tool exec yet |
| Per-tenant LLM ceiling overrides | Production-hardening | Q1 | Column on `clients`; browser UI in Aiden Settings; per-call gate honors override |
| RBAC granularity for config CRUD | Production-hardening | Q5 | New `llm_config:create/update/delete` keys (or rationale to keep `system:admin`); operator-vs-admin separation |

### Beta SHOULD-HAVE

These items target Beta but may slip to a Beta-2 or Loop 12 if scope pressure warrants.

| Item | Theme | Origin question | Notes |
|---|---|---|---|
| Aiden persona library / template profiles | Capability — Aiden | Q6, theme #5 | Operator-tunable role-default persona prompts with versioning |
| Aiden conversational mode v2 | Capability — Aiden | theme #5 | Multi-turn persona-aware chat; stateful "remember the prior brief" |
| Per-operator scratch / pinned workspace concept | Workspace | δ Q11 | Per-operator subtree under tenant root; pinned items |
| PPTX/PDF preview rendering in browser | Workspace | from δ R-035 | In-browser thumbnail + first-page preview |
| Multi-file batch workspace upload | Workspace | from δ deferred | Upload N files at once; mime-detected |
| Stuck-WO diagnosis service | Roadmap #14 | not surfaced before | Surfaces blocked WOs + likely causes; replaces manual audit-log walking |
| Audit log durability v2 (monthly partitioning maintenance) | Production-hardening | Loop 2 deferred R-old | Rolling partition creation + retention policy |

### Beta EXPLICIT DEFERRALS

These do **not** enter Beta. If any becomes a hard dependency for a must-have, flag explicitly per Stage 0 H3 discipline.

- Streaming LLM responses (request/response only stays canonical).
- Live MCP/tool **execution** (registry shape only in Beta; execution path is post-Beta).
- Cost-aware provider arbitration runtime (data model may exist as part of registry; no arbitration logic).
- Cross-channel identity merging (one identity per (client, channel, external_id)).
- Multi-region deployment / HA / disaster recovery (GA scope).
- Pixel-perfect IWO2 modal parity (operator-clarity bar already met).
- Telegram offset durable persistence (R-022; offset reset on worker restart still acceptable post-β.5 idempotency hardening).

## D. Entry assumptions

Beta relies on these guarantees from prior closures:

1. **Alpha runtime** (α.2/3/4) — Tier 1 / 1.5 / 2 invocation, token budgets, audit emission. Beta extends, doesn't replace.
2. **Channel layer** (α.5/6, ADR-022/023) — `channel_identities` + `channel_messages` + auth-code + Telegram adapter. Slack reuses the same shape.
3. **Gamma live + dual-gate** (Loop 9, ADR-020) — Sandbox follows the same gating model; non-Gamma symmetry was an explicit α.5 acceptance criterion.
4. **RBAC + RLS forced** (Loop 4, ADR-014/015). Beta adds permissions; doesn't reshape the model.
5. **Audit log + 100-event vocabulary**. Beta locks new packs (`BETA_PHASE_*_AUDIT_EVENTS`) per existing convention.
6. **Workspace data model** (Loop δ.1, migration 0014) — `workspace_folders` + `artifacts.workspace_folder_id`. Beta extends the artifact substrate; doesn't fork it.
7. **Aiden persona** (Loop δ.5) — IWO2-true voice on `aiden_tier_1`. Beta operator persona library builds on this contract.
8. **Runtime stability** (γ.6 `scripts/iwo3.sh`). Beta documents incremental changes; doesn't replace the runner.

What stays caveated (carried into Beta):

- **R-034 — drag-drop activation caveat.** The `streamlit-sortables` import probe activates literal drag-drop only after `uv sync` runs on a network-connected host. Beta does not consume this; carry as operational caveat per architect note.
- **R-021 — per-WO LLM ceiling enforced at call-time only.** Beta's must-have "per-tenant ceiling overrides" partially addresses; the timing-window risk remains if not fully redesigned.
- **R-022 — Telegram offset in-process.** Beta may resolve via a `channel_identities.last_offset` column if it adds value; not gating.

## E. Risk alignment

### Beta will retire (target)

| Risk | How |
|---|---|
| R-021 (S1) — per-WO LLM ceiling at call-time | Per-tenant override + tighter pre-flight gate; reclassifies as monitor-only |
| R-024 (S2) — Telegram bot token loss → outbound stall | `/health/channels` makes resolution visible; operator gets fast feedback |
| R-025 (S2) — workflow launch deferred from chat | Chat get the same "Open Workflow" deep-link path that browser uses; chat can launch via context resolver |
| R-027 (S3) — config CRUD RBAC granularity | Beta must-have "RBAC granularity for config CRUD" closes this |
| R-028 (S3) — dev bearer auth in production | Production auth must-have closes this |
| R-029 (S2) — `system:admin` only RBAC gate on llm_config CRUD | Same |
| R-031 (S3) — no persona library | Beta should-have "Aiden persona library" closes this if it ships |
| R-033 (S3) — client-side idempotency only | Beta must-have "server-side WO idempotency" closes this |
| R-035 (S3) — workspace file content not fetchable | Beta must-have "workspace file content fetch route" closes this |
| R-036 (S3) — workspace soft-deleted folders accumulate | Beta must-have "workspace hard-delete model" closes this |

### Beta will carry forward (does not retire)

| Risk | Why not |
|---|---|
| R-022 (S2) — Telegram offset in-process | Operationally bounded after β.5 idempotency hardening; Beta may touch but not gating |
| R-023 (S2) — auth-code consume on bypass connection | Architectural by design (cross-tenant lookup); annotated; no Beta change planned |
| R-026 (S3) — RBAC granularity carried decision | Resolved by Beta must-have if architect chooses fine-grained; otherwise deliberate carry |
| R-030 (S3) — display_name backfill is heuristic | Cosmetic; new tenants seeded explicitly post-δ |
| R-032 (S3) — chat context in-process Streamlit session state | Beta must-have "cross-session chat context durability" retires this |
| **R-034 — drag-drop activation caveat** | **Operational caveat per architect 2026-04-25; not consumed by Beta unless dep install + verification scoped** |

## F. Acceptance criteria

Beta is complete only when **all** of the following are true:

1. Production auth replaces dev bearer in production env; dev path remains for local development behind an env flag.
2. Provider keys are encrypted at rest; rotation flow demonstrated.
3. Slack adapter operates concurrently with Telegram against the same intent dispatcher; both pass F2 verification flows on a real bot.
4. Sandbox PPTX/PDF live adapter passes the same dual-gate + async polling flow Gamma does.
5. Chat creates a WO via correlation_id; a duplicate concurrent attempt with the same correlation_id is server-side-rejected (409) without creating a duplicate row.
6. Refreshing the browser preserves chat history per (operator, tenant); follow-up "where is the output?" still resolves contextually.
7. `GET /workspace/files/{id}/content` returns the right payload for txt / md / json / csv / png / jpg; UI renders inline.
8. Admin can hard-delete a workspace folder + its contents with audit emission and an "are you sure" confirm; soft-delete remains default for non-admin paths.
9. `/health/channels` + `/health/llm` return structured health for token resolution + worker liveness.
10. Tool/MCP registry v1: a new tenant-scoped table + read-only browser surface lists tool definitions + per-agent ACL state; no execution path required for Beta close.
11. Per-tenant LLM ceiling override: column on `clients`; Aiden Settings has the editor; per-call gate honors the override.
12. RBAC granularity for config CRUD: either fine-grained keys land OR an explicit ADR justifies keeping `system:admin` and the carry-forward is recorded.
13. All carried questions (8 + 3) either answered with code or explicitly punted with rationale.
14. Beta closeout artifact written (record + risk register v0.3.0 + ADRs).
15. CI green; live verification re-run for the must-have set.

## G. Loop split recommendation

**Recommendation: split MegaLoop Beta into two bounded loops.**

### Why split

- **Risk profile difference.** Production auth + encrypted credentials is security-sensitive and review-heavy. Capability expansion (Slack, Sandbox, MCP) is integration-heavy and depends on external systems being available. Mixing them lengthens review cycles and dilutes attention.
- **Dependency ordering.** Production auth + webhook endpoints + server-side idempotency + health surfaces are foundations that the second loop's adapters (Slack, Sandbox) depend on. Sequential is cleaner.
- **Reviewability.** A single MegaLoop covering 14 must-haves is hard to review at the end. Two ~7-must-have loops let CODEX gate each independently.
- **Pattern consistency.** Alpha was one MegaLoop with 8 phases. Pre-Beta split into β + γ + δ. Beta following the split pattern preserves loop discipline.

### Proposed split

**MegaLoop Beta-1 — Production Posture** (recommended order: first)

Must-have: production auth, encrypted creds, channel webhook design, server-side WO idempotency, cross-session chat context, workspace content fetch + hard-delete, `/health/*`, per-tenant LLM ceiling overrides, RBAC granularity for config CRUD.

Should-have: persona library v1, audit-log durability v2.

Defer to Beta-2: Slack live, Sandbox live, MCP registry, Aiden conversational v2.

Acceptance: 9 production-grade gates close; operator can credibly hand IWO3 to a non-development pilot tenant.

**MegaLoop Beta-2 — Capability Expansion** (second)

Must-have: Slack adapter live, Sandbox PPTX/PDF live, Tool/MCP registry v1 shape, Aiden conversational mode v2.

Should-have: stuck-WO diagnosis service, PPTX/PDF preview in workspace, multi-file batch upload, per-operator scratch concept.

Acceptance: second channel + second output adapter operate; tool registry visible; Aiden chat is multi-turn.

### Alternative: single MegaLoop Beta

If CODEX prefers one loop: 14 must-haves + 7 should-haves + closeout. Estimated ~10–14 internal phases. Higher coordination cost but single closeout artifact set.

**My recommendation:** split. The architect's "decide whether Beta should be a single MegaLoop or split into two bounded loops" question maps cleanly to the precedent: Alpha was one MegaLoop with 8 phases and was tight; this set of must-haves is bigger and has natural seams. Two bounded loops match the existing β/γ/δ rhythm better than one large MegaLoop.

## H. What the prestart questions cover

The companion `IWO3_MEGALOOP_BETA_PRESTART_QUESTIONS_v0.1.0.md` opens:

- The 8 carried architect questions (auth choice, webhook design, RBAC granularity, persona library, etc.)
- The 3 new Loop δ questions (workspace content fetch shape, hard-delete model, per-operator scratch)
- 4 new Beta-only questions:
  - Beta loop-split decision (single MegaLoop vs Beta-1 + Beta-2)
  - Tool/MCP registry v1 scope ceiling
  - Slack adapter timing (Beta-1 or Beta-2)
  - Encrypted-at-rest credential mechanism (libsodium / AWS KMS / GCP KMS / pgcrypto)

CODEX must answer these before Beta-1 (or single-loop Beta) coding starts.

## I. Carried operational caveats

- **R-034 — drag-drop activation caveat.** Carried, not consumed. Visible in Risk Register v0.2.3 and v0.3.0 (Beta closeout) until the operator runs `cd apps/console-streamlit && uv sync` and verifies literal drag-drop on a networked host. **Not a Beta gate.**
- **Markdown lint warnings** (MD040/MD060/MD029) on governance docs. Cosmetic.
- **Streamlit smoke-warning logs** during pytest runs. Already documented in conftest.py; harmless.

## J. Out-of-scope explicitly

- Reopening any closed Alpha or δ work without a justified Beta dependency.
- "Polish" work that doesn't tie to a must-have or should-have above.
- Introducing new architectural primitives (new top-level tables / new tier / new audit-loop pack) without an ADR.

---

This proposal is a **draft for CODEX review**. Coding is not authorized until the prestart questions are answered and the loop-split decision is locked.
