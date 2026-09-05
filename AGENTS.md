# AGENTS.md — AIDEN_IWO3

Agent rules for any AI working in this codebase. MUST/SHOULD format. Read
before making changes.

> **Corrected 2026-09-05 (Loop Omicron, ο.8).** This file previously
> identified the codebase as `AIDEN_IWO2` and every rule below §"Inherited
> IWO2 rules" describes the IWO2 Express/TypeScript runtime, which does not
> exist here. The identity and runtime sections are corrected; the inherited
> block is demarcated rather than deleted, because some of those rules encode
> real architectural decisions whose IWO3 equivalents have not yet been
> established. Auditing them one by one is a successor-loop task, not a
> banking commit.

## This codebase (IWO3) — MUST

- MUST NOT commit `.env` or any API key. Credentials are referenced as
  `credential_ref:env:NAME`; the value never enters source control.
- MUST NOT run pytest against a non-`_test` database. `apps/api-fastapi/tests/conftest.py`
  refuses it; overriding with `IWO3_ALLOW_NON_TEST_DB` requires operator
  authorization. A fixture running against the operator DB has already
  destroyed live tenant configuration once (BUG-081).
- MUST place Aiden rules that have to hold for **every tenant** in
  `_AIDEN_OUTPUT_SCHEMA_TEMPLATE`, never in `AIDEN_SYSTEM_PROMPT` — a tenant
  with a custom `llm_configs.system_prompt` replaces the persona wholesale, so
  a rule written there is dead code for that tenant (CR-014, BUG-083).
- MUST NOT hardcode health dashboard values or KPIs, and MUST make a health
  check resolve what it claims rather than count a row next to it (BUG-082).
- MUST validate the `provider` + `credential_ref` pair on every `llm_configs`
  write path; `tests/test_llm_config_write_path_invariants.py` fails when a new
  write path skips the guard (BUG-080).
- MUST declare `required_permission` on any tool that mutates state; tool-
  mediated actions are authorized the same as the equivalent HTTP route.
- MUST validate a new test gate by reintroducing the defect it guards. A gate
  never observed to fail is not a gate.

## This codebase (IWO3) — runtime facts

| Component | Detail |
| --- | --- |
| API | FastAPI — `apps/api-fastapi`, `uvicorn main:app`, port **8000** |
| Console | Streamlit — `apps/console-streamlit`, `Home.py`, port **8501** by convention; **8502 locally** because DigiFlow (WS021) holds 8501 |
| Database | Postgres 16 in `aiden-iwo3-postgres`, port **5434**, db `aiden_iwo3` |
| Test database | `aiden_iwo3_test` — the only database the suites may target |
| Start / stop | `bash scripts/iwo3.sh up\|down\|status` (note: `status` reports a false green for the console when DigiFlow holds 8501) |
| Auth | `IWO3_AUTH_MODE` unset ⇒ `dev_bearer` (`X-IWO3-User` / `X-IWO3-Client` headers) |
| Migrations | `db/migrations/*.sql`; `infra/local/apply-migrations.ts` **replays from 0000** and fails on an existing database (applied-state enforcement is Omicron.9) |

The IWO2 Express/TypeScript runtime — `server/orchestration.ts`,
`server/pocketflow.ts`, port 5001, `npm run dev` — is **not this codebase**.
It lives in `/home/virgina/VS_AIDEN_IWO2`.

---

## Inherited IWO2 rules (historical — verify before applying to IWO3)

Everything below arrived with the IWO2 baseline and refers to the Express
runtime above. Do not apply a rule from this section to IWO3 without first
confirming the file and function it names exist here. Auditing this block into
IWO3 equivalents is tracked as a successor-loop item.

## Critical Rules (MUST)

- MUST read `BUGFIX_LOG.md` before modifying `server/orchestration.ts` or `server/pocketflow.ts`. Known bugs and architectural decisions are documented there.
- MUST read `ADR-001` in `BUGFIX_LOG.md` before touching `nodeBuildResponse()` in `pocketflow.ts`. The assembly strategy is intentional — do not revert or "improve" it without understanding the delta_overlay deferral decision.
- MUST NOT revert BUG-025 fix in `nodeBuildResponse`. The `latest-iteration-wins` assembly for general documents is the current platform contract.
- MUST NOT implement `delta_overlay` (artifact_key / refine_mode on PlanStep) without a full session scoped to ADR-001. It requires data model + LLM prompt + assembly changes together — partial implementation is worse than none.
- MUST use `let`, not `const`, for `tier2Result` in `orchestration.ts` — it is reassigned in the auto-revision loop.
- MUST NOT change `createTableIfMissing: true` in the session store config to `false`.
- MUST NOT commit `.env` or any API keys.
- MUST NOT remove the `isIntermediateOutput()` filter in `nodeBuildResponse` — it prevents planning/status text from appearing in deliverables.
- MUST NOT replace the ESM `__dirname` polyfill in `pocketflow.ts` with bare `__dirname`.
- MUST pass `postProcessedFile` as the 9th argument to `runAidenQualityReview()` in `orchestration.ts` — omitting it causes Aiden to incorrectly flag binary deliverables (PDF/PPTX) as invalid.
- MUST NOT remove or bypass the Done Contract gate in `completeAndFileWorkOrder()` — it is the last deterministic closeout check before terminal status.
- MUST NOT hardcode health dashboard values or KPIs — always derive from real runtime state (DB queries, env var checks, connectivity tests).
- MUST NOT remove the PPTX preflight validator or slide source shaper from `nodePostProcess()` — they prevent weak content from reaching Gamma.
- MUST propagate execution-profile flags (`promptCompaction`, `batchedSynthesis`, `reviewReduction`) via `SharedDict` fields, not via closure-scoped `options`. Node functions (`nodeExecStep`, `nodeEvaluate`, etc.) are module-level and cannot access `pocketflowExecute`'s parameters.
- MUST NOT bypass the execution-strategy resolver in `processWorkOrder()` — it runs after Tier 1 approval and before direct dispatch. The resolver is deterministic and auditable; removing it breaks workflow routing.
- MUST NOT allow duplicate active workflow executions for the same work order — the double-execution guard in `processWorkOrder()` prevents this.

## PocketFlow Tuning (current values — MUST NOT change without operator approval)

| Parameter | Value | Location |
| --- | --- | --- |
| `maxIterations` | 9 | `orchestration.ts` |
| `convergenceThreshold` | 0.75 | `orchestration.ts` |
| `maxAutoRevisions` | 4 | `orchestration.ts` |

## Architecture Decisions (SHOULD know)

- **ADR-001:** PocketFlow assembly is `latest-iteration-wins` for general documents. Full `delta_overlay` (stable artifact identity across iterations) is the correct long-term architecture but is deferred to v0.5+. See `BUGFIX_LOG.md` for the full design note including CODEX analysis and 7 acceptance tests.
- **PDF rendering:** Playwright Chromium only (`server/scripts/html-to-pdf.cjs`). Chromium sourced from `PLAYWRIGHT_PATH` env var or `/home/virgina/claude-office-skills/node_modules/playwright` fallback. LibreOffice is on the system but NOT in the PDF pipeline — do not route PDF work orders through it.
- **Done Contract:** `server/done-contract.ts` evaluates closeout for 4 artifact tracks (static_web_page, software_artifact, document, pptx). Includes governed "Wrap It Up" HITL override. Gate is inside `completeAndFileWorkOrder()`.
- **PPTX quality pipeline:** `server/pptx-quality.ts` — preflight validator, contract parser, post-Gamma compliance, slide source shaper, review supplement. Wired into `nodePostProcess()` in `pocketflow.ts`.
- **Auth:** GET /api/login (dev auto-login) blocked unless `NODE_ENV=development`. Password auth via POST /api/login. Bootstrap admin via `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD` env vars.
- **Startup validation:** `server/env-check.ts` — hard-blocks boot on missing `DATABASE_URL`, `SESSION_SECRET`, or all LLM keys. Warns on optional vars.
- **Ports (IWO2 runtime, not this codebase):** AIDEN_IWO2 runs on port 5001; AIDEN_IWO (legacy) on 5000. IWO3's own ports are in the runtime-facts table above.

## Safe Change Zones (SHOULD)

- SHOULD check `ROADMAP_FEATURES_v2.2.md` before adding new features — may already be planned or scoped.
- SHOULD update `BUGFIX_LOG.md` when fixing any bug, including severity, root cause, and fix summary.
- SHOULD update session notes in `CLAUDE.md` at the end of any session that changes behavior.
- SHOULD keep `CLAUDE.md`, `AGENTS.md`, and `BUGFIX_LOG.md` in sync on architectural decisions.

## Known Open Architecture Items

| Tag | Item | Status |
| --- | --- | --- |
| ADR-001 | PocketFlow delta_overlay assembly (artifact_key + refine_mode) | Deferred to v0.5+ |
| BUG-048 | PocketFlow options-scope regression — execution-profile flags must live on SharedDict, not closure scope | Fixed (2026-03-21) |
| ESR-001 | Execution Strategy Resolver — deterministic workflow template matching after Tier 1 | Shipped (2026-03-21) |
| BUG-054 | Know-How parser: article blindness + missing bare folder detection + narrow Chat trigger. Universal fix in shared parser. | Fixed (2026-03-27, Loop 15) |
| BUG-055 | Know-How name search timeout: ILIKE on content column scanning base64 blobs. Fix: name-only search. | Fixed (2026-03-28, Loop 18) |
| BUG-056 | WO-generated artifacts polluting retrieval. Fix: source-over-derivative scoring via `isWoGeneratedArtifact()`. | Fixed (2026-03-28, Loop 19) |
| FEAT-006 | Universal text extraction service (`server/text-extractor.ts`). Registry pattern: PDF/DOCX/PPTX. Add new formats via `registerExtractor()`. | Shipped (2026-03-28, Loop 17) |
| FEAT-007 | Chat workspace awareness: `buildWorkspaceIndex()` live directory tree in system prompt. | Shipped (2026-03-28, Loop 20) |
| FUTURE | Consider removing Chat Know-How trigger gate — rely solely on `parseContextRequestFromChat` returning `null` for irrelevant messages. Would eliminate trigger/parser mismatch class of bugs. | Noted (2026-03-27) |
| FUTURE | Content(i) formal classification (`content_class` column replacing `isWoGeneratedArtifact()` heuristic). Phase 2 of Know-How Evolution Plan. | Planned |
