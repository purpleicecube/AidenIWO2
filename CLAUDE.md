# CLAUDE.md — AIDEN_IWO

## Overview

AIDEN_IWO (Intelligent Work Orchestration) is a 2-tier AI agent platform. Tier 1 (Aiden) is the orchestrator/policy engine. Tier 2 (sub-agents) execute work orders via PocketFlow. Built on Express 5 + React 18 + PostgreSQL + Drizzle ORM.

### Product Lineage

Both AIDEN_IWO and AIDEN_TIB derive from the base **AIDEN_ALPHAv3** prompt specification. IWO is the full-stack runtime platform (this repo). TIB (The Internal Brain) is the spec-level agent architecture (sub-agent definitions, BDM routing, delegation protocols). TIB will become a **specialized branch** of a future IWO version — it is not a separate product. IWO is the broader, more versatile platform.

- **Version:** v0.9.9 (alpha)
- **Repo:** `purpleicecube/AidenIWO-or-TIB` (branch: `main`)
- **Local path:** `/home/virgina/VS_AIDEN`
- **Related workspace:** `VS_PDOE/WS006_AIDEN(GLOBAL)`
- **Spec repo:** `purpleicecube/aiden_alpha_spec` (`/home/virgina/aiden_alpha_spec`, branches: `main`, `v3.x`)

## Local Dev Environment

| Component | Detail |
| --- | --- |
| App URL | <http://localhost:5001> |
| Login | `POST /api/login` (email + password) or `GET /api/login` (auto-login fallback) at <http://localhost:5001/api/login> |
| Node.js | v20.20.0 via nvm (pinned in `.nvmrc`) |
| Database | Docker container `aiden-postgres` on port 5433 |
| DB credentials | user=`aiden`, pass=`aiden_local`, db=`aiden_iwo` |
| Docker volume | `aiden_pgdata` (persistent, survives reboots) |
| Restart policy | `unless-stopped` |
| Backups | Daily at 2:00 AM, 7-day retention, in `backups/` |

### Start/Stop

```bash
./script/local-dev.sh start   # DB + schema + dev server
./script/local-dev.sh stop    # Stop everything
./script/local-dev.sh status  # Show what's running
./script/local-dev.sh reset   # DESTRUCTIVE — deletes all data
```

### Key npm Commands

```bash
npm run dev       # Dev server (Express + Vite, auto-loads .env)
npm run db:push   # Push Drizzle schema to Postgres
npm run build     # Production build
npm run check     # TypeScript type check
```

## Architecture

### 2-Tier System

- **Tier 1 (Aiden):** Policy gate, routing, quality review, approval. Uses Groq (`openai/gpt-oss-120b`).
- **Tier 2 (Sub-agents):** Execute work orders via PocketFlow. Each sub-agent has its own LLM config (provider, model, system prompt). Currently A010_Project Manager Alpha uses OpenRouter (`google/gemini-2.5-pro-preview`).

### Work Order Pipeline

```text
Submit → Tier1 Policy Gate → Route to Sub-Agent → PocketFlow Engine:
  PlanSteps (LLM) → ExecStep×N (LLM, parallel if no deps) →
  Evaluate (LLM) → [Refine loop if score < threshold] →
  BuildResponse → Tier1 Quality Review → [Auto-revision loop if needed] →
  Complete + File to Workspace
```

### PocketFlow Tuning Parameters

| Parameter | Location | Default | Purpose |
| --- | --- | --- | --- |
| `maxIterations` | `orchestration.ts:257` | 3 | Max plan→exec→eval→refine loops |
| `convergenceThreshold` | `orchestration.ts:257` | 0.8 | Min eval score to accept output |
| `maxAutoRevisions` | `orchestration.ts:381` | 2 | Max Tier 1 quality-triggered re-executions |

## Key Files

| File | Purpose |
| --- | --- |
| `server/orchestration.ts` | Main work order processing pipeline |
| `server/pocketflow.ts` | PocketFlow engine (plan, exec, evaluate, refine, build) |
| `server/llm-client.ts` | LLM provider abstraction + all LLM call functions |
| `server/routes.ts` | All API routes (2300+ lines) |
| `server/storage.ts` | Database access layer |
| `server/workspace-filing.ts` | Auto-files deliverables into workspace folders |
| `server/replit_integrations/auth/replitAuth.ts` | Auth (rewritten for local auto-login) |
| `server/seed.ts` | Seeds sample data on empty DB only (safe — checks before inserting) |
| `shared/schema.ts` | All Drizzle table definitions |
| `shared/models/auth.ts` | Sessions + users table schemas |
| `client/src/pages/landing.tsx` | Login page |
| `client/src/hooks/use-auth.ts` | Auth state polling hook |
| `.env` | Environment variables (git-ignored) |
| `.nvmrc` | Pinned Node.js version |
| `server/scripts/md-to-pptx.py` | Markdown to PPTX conversion script (python-pptx) |
| `server/scripts/html-to-pdf.cjs` | HTML to PDF conversion via Playwright Chromium (called by `nodePostProcess` for PDF work orders) |
| `BUGFIX_LOG.md` | Bug fixes, code review findings, performance analysis |
| `ROADMAP_FEATURES_v2.2.md` | Full features inventory and roadmap (active versioned file) |

## Database Tables (key ones)

| Table | Purpose |
| --- | --- |
| `work_orders` | All work orders with status, results, GCC memory |
| `execution_logs` | Full audit trail per work order |
| `sub_agents` | Tier 2 agent configs (LLM provider/model/prompt per agent) |
| `llm_settings` | Global Tier 1 LLM config (singleton, id=`default`) |
| `operational_settings` | System-wide governance rules |
| `sessions` | Express session store (connect-pg-simple) |
| `users` | User accounts |
| `artifact_folders` | Workspace folder tree |
| `artifacts` | Files/deliverables stored in workspace |
| `workflow_templates` | Saved multi-step workflows |
| `skill_templates` | Prompt/skill templates |
| `tools` | Registered tools (MCP, scripts, etc.) |
| `chat_sessions` / `chat_messages` | Aiden chat history |
| `gamma_settings` | Gamma global config (singleton, id=`default`) — `templateKey` points to registry |
| `gamma_template_registry` | Approved Gamma templates with friendly keys, content contracts, mode enforcement |
| `gamma_generation_records` | Audit trail per Gamma run + candidate tracking (templateKey, gammaId, status, candidateStatus, candidateGroup, artifactFiledPath) |

## API Endpoints (most used)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/login` | Auto-login (local dev) |
| GET | `/api/auth/user` | Current authenticated user |
| GET | `/api/work-orders` | List work orders |
| POST | `/api/work-orders` | Create work order |
| POST | `/api/work-orders/:id/process` | Trigger processing |
| POST | `/api/work-orders/:id/retry` | Retry failed work order |
| GET | `/api/sub-agents` | List sub-agents |
| PUT | `/api/sub-agents/:id` | Update sub-agent config |
| GET | `/api/llm-settings` | Get Tier 1 LLM settings |
| PUT | `/api/llm-settings` | Update Tier 1 LLM settings |
| POST | `/api/workspace/seed` | Initialize workspace folders |
| GET | `/api/artifact-folders` | List workspace folders |

## LLM Provider Keys

Configured in `.env`. Sub-agents reference keys by env var name:

| Provider | Env Var | Used By |
| --- | --- | --- |
| Groq | `GROQ_API_KEY` | Tier 1 (Aiden) |
| OpenRouter | `OPENROUTER_API_KEY` | A010_Project Manager Alpha |
| OpenAI | `OPENAI_API_KEY` | Not currently configured |
| Anthropic | `ANTHROPIC_API_KEY` | Not currently configured |
| Gamma | `GAMMA_API_KEY` | PPTX generation (per-template, optional) |

## Gamma Integration (PPTX + PDF)

Gamma is an external presentation/document generation service used for high-quality, Klear.ai-branded PPTX and PDF output. Both formats route through the same Gamma engine, managed via a **Template Registry** with content contracts and audit trail.

### Three-Layer Model

| Layer | Controls | Where It Lives |
| --- | --- | --- |
| **Gamma Template** | Look — colors, fonts, logo, slide/page layout | Gamma (external, `gammaId`) |
| **Content Contract** | Fit — slide/page count, required sections, forbidden patterns, tone | `gamma_template_registry.contentContract` |
| **LLM Prompt** | Implements the contract | Injected into `llmPlanSteps()` + `llmExecStep()` via `designContext` |

### Gamma Template Registry

Approved Gamma templates are managed through the `gamma_template_registry` table. Each entry has a friendly `templateKey`, the external `gammaId`, an `outputFormat` (pptx or pdf), a `mode` (template_locked or flexible), and an optional `contentContract`.

**Current registered templates:**

| templateKey | gammaId | Format | Mode | Name |
| --- | --- | --- | --- | --- |
| `klear_live_v1` | `g_onfwfqpb52zcws3` | PPTX | template_locked | Klear.ai Live Template v1 |
| `klear_pdf_v1` | `g_122ahx4j0eer8lz` | PDF | template_locked | Klear.ai PDF Template v1 |

### How Routing Works

Policy is resolved **early** in `pocketflowExecute()` — before planning or execution — so the content contract influences LLM output, not just post-processing.

1. **Detect format:** `detectRequiredFormat()` checks WO title/description for "pdf"/"pptx" keywords and skill assignments.
2. **Resolve templateKey:** Workflow template `gammaTemplateKey` → global `gamma_settings.templateKey` → legacy `gammaId` fallback.
3. **Format-aware lookup:** If the resolved registry entry's `outputFormat` doesn't match the detected format, the system searches all approved entries for a format-matched alternative (e.g., PPTX default swaps to `klear_pdf_v1` for a PDF WO).
4. **Policy stored on SharedDict:** `dict.gammaPolicy` carries `templateKey`, `resolvedGammaId`, `mode`, `outputFormat`, `contentContract`, `fallbackAllowed` through the entire execution.
5. **Content contract injected:** If present, `dict.designContext` is set from the registry entry's `contentContract` and injected into LLM prompts as `=== CONTENT CONTRACT ===`.
6. **Post-process uses policy:** Both PPTX and PDF `nodePostProcess()` blocks read `dict.gammaPolicy` directly — no re-resolution from DB.

**Enforcement (template_locked mode):**

- If Gamma fails and mode is `template_locked`: WO is **blocked** — no silent fallback to local.
- If mode is `flexible`: falls back to local pipeline on failure.

### Generation Records (Audit Trail + Candidate Tracking)

Every Gamma generation (success or failure) writes a `gamma_generation_records` row:

- `workOrderId`, `templateKey`, `gammaId`, `exportFormat`, `status`
- `generationId`, `gammaUrl`, `fileSize`, `creditsDeducted`, `creditsRemaining`
- **Candidate fields:** `candidateStatus` (candidate/selected/rejected), `candidateGroup` (UUID), `artifactFiledPath` (durable path), `selectedAt`, `selectedBy`
- Query: `GET /api/gamma-generations?workOrderId=X`
- Candidates: `GET /api/work-orders/:id/candidates`

### Configuration

#### Registry Management (Recommended)

```bash
# List all registered templates
curl -s -b /tmp/aiden-cookie.txt http://localhost:5001/api/gamma-templates

# Get by key
curl -s -b /tmp/aiden-cookie.txt http://localhost:5001/api/gamma-templates/klear_live_v1

# Register new template
curl -X POST http://localhost:5001/api/gamma-templates \
  -H "Content-Type: application/json" \
  -b /tmp/aiden-cookie.txt \
  -d '{
    "templateKey": "klear_live_v1",
    "gammaId": "g_onfwfqpb52zcws3",
    "name": "Klear.ai Live Template v1",
    "outputFormat": "pptx",
    "mode": "template_locked",
    "contentContract": "Slides: 5-8\nRequired sections: Cover, Executive Summary, 2-4 content slides, Thank You"
  }'

# Update (e.g., retire a template)
curl -X PUT http://localhost:5001/api/gamma-templates/{id} \
  -H "Content-Type: application/json" \
  -b /tmp/aiden-cookie.txt \
  -d '{"status": "retired"}'
```

#### Global Settings

```bash
# View current settings (includes templateKey for registry routing)
curl -s -b /tmp/aiden-cookie.txt http://localhost:5001/api/gamma-settings

# Set global templateKey (preferred over raw gammaId)
curl -X PUT http://localhost:5001/api/gamma-settings \
  -H "Content-Type: application/json" \
  -b /tmp/aiden-cookie.txt \
  -d '{"templateKey": "klear_live_v1"}'

# Test Gamma API connectivity
curl -X POST -b /tmp/aiden-cookie.txt http://localhost:5001/api/gamma-settings/test
```

### API Endpoints

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/api/gamma-settings` | viewer | Read settings + API key status |
| PUT | `/api/gamma-settings` | admin | Update global Gamma config |
| POST | `/api/gamma-settings/test` | admin | Test Gamma API connectivity |
| GET | `/api/gamma-templates` | viewer | List all registered templates |
| GET | `/api/gamma-templates/:key` | viewer | Get template by templateKey |
| POST | `/api/gamma-templates` | admin | Register new template |
| PUT | `/api/gamma-templates/:id` | admin | Update template (status, name, etc.) |
| GET | `/api/gamma-generations?workOrderId=X` | viewer | Generation audit records for a WO |
| GET | `/api/work-orders/:id/candidates` | viewer | List Gamma candidates for a WO |
| POST | `/api/work-orders/:id/candidates/:recordId/select` | operator | Select a candidate (rejects others, resumes completion) |
| POST | `/api/work-orders/:id/candidates/:recordId/reject` | operator | Reject a single candidate |
| POST | `/api/work-orders/:id/candidates/reject-all` | operator | Reject all candidates |
| POST | `/api/work-orders/:id/candidates/request-more` | operator | Re-run PocketFlow for more candidates |
| GET | `/api/gamma-candidates/:recordId/download` | viewer | Download candidate file |

### Observability

- **Generation records** — full audit trail per Gamma run: `GET /api/gamma-generations?workOrderId=X`
- **Execution logs** include `engine: "gamma"`, `templateKey`, `generationId`, `gammaUrl`, `creditsDeducted`, `creditsRemaining`
- **2DO Checklist** items show "PPTX/PDF generated via Gamma [templateKey] (XXkB, N credits)"
- **Server console** logs `[pocketflow] Resolved templateKey "X" → gammaId "Y" (mode, format)` on every resolution

### Gamma Files

| File | Purpose |
| --- | --- |
| `server/gamma-client.ts` | Gamma REST API client (generate, poll, download) |
| `server/pocketflow.ts` | Early policy resolution, `nodePostProcess()` PPTX+PDF blocks, generation records |
| `server/llm-client.ts` | `designContext` param in `llmPlanSteps()` + `llmExecStep()` — injects content contract |
| `shared/schema.ts` | `gammaTemplateRegistry`, `gammaGenerationRecords`, `gammaSettings` tables |
| `server/storage.ts` | Registry CRUD, generation record writes, settings methods |
| `server/routes.ts` | Registry + generation + settings API endpoints |

### Constraints

- Gamma API key lives only in `.env` — never stored in DB or logged
- Export URLs from Gamma expire — the client downloads immediately after generation completes
- Each generation consumes Gamma credits — tracked in generation records for cost monitoring
- Branding must live in the Gamma template, not in a raw .pptx file
- `template_locked` mode blocks fallback on failure — use only for approved branded templates
- Legacy `gammaTemplateId`/`gammaId` columns still work (backward compatible) but `gammaTemplateKey`/`templateKey` via registry is preferred

## Data Persistence

All configuration (LLM settings, sub-agent configs, prompts, templates, operational settings) is stored in PostgreSQL and survives restarts. `seed.ts` only runs on empty databases — it never overwrites existing data.

The Docker volume `aiden_pgdata` persists across container restarts and reboots. Daily backups to `backups/` provide an additional safety net (7-day rotation).

## Rules

- Never commit `.env` or any API keys.
- Always check `BUGFIX_LOG.md` before modifying `orchestration.ts` or `pocketflow.ts` — known issues are documented there.
- The auth file is at `server/replit_integrations/auth/` but no longer uses Replit auth. It's local auto-login.
- `createTableIfMissing: true` in the session store config — do not change back to `false`.
- `tier2Result` in `orchestration.ts` must be `let`, not `const` — it gets reassigned in the revision flow.
- Non-HTML deliverable assembly in `pocketflow.ts` filters intermediate outputs via `isIntermediateOutput()` — do not remove this filter.
- **ADR-001 (read before touching `nodeBuildResponse`):** PocketFlow assembly is currently `latest-iteration-wins` for general documents (BUG-025 fix). This is intentional and known to be a partial fix. The full `delta_overlay` architecture (artifact_key + refine_mode per step) is deferred to v0.5+. Do NOT revert BUG-025 and do NOT implement delta_overlay without reading ADR-001 in `BUGFIX_LOG.md` first.
- PocketFlow tuning: `maxIterations=9`, `convergenceThreshold=0.75`, `maxAutoRevisions=4` (updated 2026-03-07).
- `pocketflow.ts` uses ESM polyfill for `__dirname` — do not replace with bare `__dirname`.
- Quality review in `llm-client.ts` accepts `postProcessedFile` param — post-processing notice goes at TOP of prompt (before deliverable) to avoid truncation.
- Workspace filing: `resolveOutputFolder()` in `workspace-filing.ts` takes `hasPostProcessedFile` flag — binary files always route to `#Documents`.
- PDF rendering uses **Playwright Chromium** (not LibreOffice) via `server/scripts/html-to-pdf.cjs`. Chromium is sourced from `/home/virgina/claude-office-skills/node_modules/playwright` — do not move or delete that package. LibreOffice is still on the system but is no longer in the PDF pipeline.
- `injectPdfStyles` in `pocketflow.ts` injects CSS with `@page { margin: 0 }` and `html, body { max-width: none !important }` to override pandoc's default narrow-body template. It also strips pandoc's `<header id="title-block-header">` element (the metadata title H1) to prevent duplication with the styled header bar.

## Session Notes

| Date | Notes |
| --- | --- |
| 2026-03-03 | Local dev environment established. Docker Postgres on port 5433, local auto-login auth, backup system (daily cron + script). Fixed 4 bugs: missing Postgres, session table creation, const reassignment crash in revision flow, JSON fragment assembly in non-HTML deliverables. 6 code review findings documented. Performance analysis: Tier 2 sub-agent latency is primary bottleneck (OpenRouter/Gemini-2.5-Pro, 15-25s per LLM call). Workspace seeded with 10 folders. |
| 2026-03-04/05 | Fixed 6 additional bugs (BUG-005 through BUG-010): Tier 1 Zod validation failure (resilient parsing with defaults), ESM `__dirname` polyfill for post-processing, quality review truncation fix (postProcessedFile param), PPTX filing routing to #Documents, workspace preview base64 gibberish (smart file category rendering with 4 modes), download endpoint for all binary types. New features: PPTX post-processing pipeline (md-to-pptx.py), smart file preview/download for all file types, skills content injection into Tier 2 prompts, password-based auth (bcryptjs). Created `ROADMAP_FEATURES.md` (123 features across 16 domains; now versioned as `ROADMAP_FEATURES_v2.2.md`). Updated BUGFIX_LOG.md, CHANGELOG.md (v0.3.8). |
| 2026-03-07 | Session 7. BUG-021: PDF artifact never generated — built end-to-end PDF pipeline (pandoc md→HTML + Playwright Chromium HTML→PDF). BUG-022: PDF layout broken with LibreOffice — switched renderer to Playwright Chromium (`server/scripts/html-to-pdf.cjs`); reworked `injectPdfStyles` for full-bleed header/footer, full-width content, pandoc body override, fixed-position footer. PDF output: 1-page professional layout, edge-to-edge dark navy header/footer. BDM evaluator fix: `llmEvaluate` now receives `platformFormat` to suppress binary-file demand for PDF/PPTX orders. Deliverable deduplication: `nodeBuildResponse` uses only last iteration output for PDF. Deliverable path UI: `GET /api/artifacts?sourceId=`, `DeliverableCard` component, `FileDown` indicator on work orders list. BUG-025: Content duplicated after multi-iteration refine loop — `nodeBuildResponse` general path now uses last iteration's step outputs only (same as PDF path). ADR-001 filed: full `delta_overlay` architecture deferred to v0.5+. PocketFlow tuning: maxIterations=9, convergenceThreshold=0.75, maxAutoRevisions=4. App renamed AIDEN_IWO2 in sidebar/landing/footer. 25 total bugs fixed. |
| 2026-03-14 | **v0.9.4 — HITL Candidate Review + Three-Level Template Precedence.** `gammaDeliveryPolicy` on `workflow_templates` (auto_revise/candidate_review). WO-level `gammaTemplateKey` override on `work_orders` (highest precedence). Candidate columns on `gamma_generation_records`: `candidateStatus`, `candidateGroup`, `artifactFiledPath`, `selectedAt`, `selectedBy`. Durable candidate persistence in `.local/gamma_candidates/{woId}/`. Orchestration gate in `orchestration.ts`: when `gammaDeliveryPolicy=candidate_review`, WO moves to `awaiting_operator` after revision loop. 6 candidate API endpoints: list/select/reject/reject-all/request-more/download. Three-level template precedence: WO > workflow > global. `gammaDeliveryPolicy` passed through Tier2Result. Storage: `getGammaGenerationRecord`, `getGammaCandidates`, `selectGammaCandidate`, `rejectGammaCandidate`, `rejectAllGammaCandidates`. |
| 2026-03-14 | **Gamma PPTX integration + Template Registry.** Added `server/gamma-client.ts` (direct REST API to `public-api.gamma.app/v1.0`). New `gamma_settings` table for global config. Added `pptx_engine`, `gamma_theme_id`, `gamma_template_id` columns to `workflow_templates` for per-template Gamma routing. Klear.ai Gamma template `g_onfwfqpb52zcws3` (PPTX) and `g_122ahx4j0eer8lz` (PDF) configured. **Gamma Template Registry:** New `gamma_template_registry` table (templateKey, gammaId, contentContract, mode, status) + `gamma_generation_records` audit table. Three-layer model: Gamma template controls look, content contract controls fit, LLM prompt implements contract. Format-aware early resolution in `pocketflowExecute()` — detects PPTX/PDF format, resolves templateKey through registry, auto-swaps to format-matched entry. `gammaPolicy` on SharedDict carries resolved policy through entire execution. Content contract injected into `llmPlanSteps()` + `llmExecStep()` via `designContext`. Both PPTX and PDF `nodePostProcess()` blocks use `dict.gammaPolicy` with generation record writes + locked template enforcement. Registry API: GET/POST `/api/gamma-templates`, GET `/api/gamma-templates/:key`, PUT `/api/gamma-templates/:id`, GET `/api/gamma-generations?workOrderId=X`. Seeded `klear_live_v1` (PPTX, template_locked) and `klear_pdf_v1` (PDF, template_locked). EVAL created at `VS_PDOE/WS006_AIDEN(GLOBAL)/05_Artifacts/EVAL_GAMMA_REGISTRY_v1.0.md`. |
| 2026-03-13 | **v0.9.2 release.** PPTX workflow readiness: replaced PPTX skill with IWO2-native md-to-pptx spec, updated TOM/PM Alpha/Mark/Paul system prompts via API for workflow orchestration. 2DO Checklist feature: `checklist_items` table + 4 endpoints + 11 lifecycle hooks + UI panel. Contract drift fix (CODEX 5.4): workflow PM completion now writes to `tier2Result` (not legacy `result`/`deliverableType` fields), synthetic WorkOrder/Tier1Result aligned to actual schema, `toolsUsed` added to Tier2Result type, `gccMemory` exposed in insert schema. 17 TS errors resolved, 50/50 tests pass. |
| 2026-03-15 | **Session 11 — Done Contract + Gamma PPTX Remediation + Pre-Replit Stabilization.** Major session with 4 bug fixes (BUG-038 through BUG-041), Done Contract implementation, runtime stabilization, and extensive PPTX pipeline hardening. **Done Contract (4 artifact tracks + Wrap It Up):** New `server/done-contract.ts` — deterministic closeout evaluator with Static Web Page, Software Artifact, Document, and PPTX tracks. Governed HITL "Wrap It Up" override mode with audit trail. Gate wired into `completeAndFileWorkOrder()`. 103 tests in `done-contract.test.ts`. **Gamma PPTX Remediation (BUG-038):** New `server/pptx-quality.ts` — PPTX preflight validator, contract parser, post-Gamma compliance checker, slide source shaper, review supplement. 6-part remediation: preflight before Gamma, contract parsing, compliance logging, PPTX-aware Aiden review, Done Contract compliance gate, source preview labeling. **BUG-039 (Critical):** Workflow post-processing safety net — `postProcessWorkflowDeliverable()` runs Gamma/local conversion on PM-assembled work product when no step produced a binary. **BUG-040:** Sub-agent routing empty-string fuzzy match fix — `findSubAgent()` was matching all agents due to `"".includes("")` === true from trailing spaces in agent names. **BUG-041:** Gamma watchdog heartbeat starvation — `onHeartbeat` callback in `generateWithGamma()` polling loop keeps WO alive during 60-150s Gamma generation. **Pre-Replit Stabilization (Track 1):** Unified version/build identity (`server/version.ts` reads from package.json), startup env validation (`server/env-check.ts` — hard-blocks on missing DATABASE_URL/SESSION_SECRET/LLM keys), published-mode auth hardening (GET /api/login blocked unless NODE_ENV=development), truthful `/api/health` endpoint (real DB/LLM/Gamma/session checks), Gamma status added to System Health UI. **Pre-Replit Stabilization (Track 2):** Local PPTX fallback reclassified as "draft quality — not Gamma-branded", PDF path verified intact, machine-local paths (`/home/virgina/claude-office-skills`) replaced with `SKILLS_DIR`/`PLAYWRIGHT_PATH` env vars with local fallback. **Observability enrichment:** 2DO checklist items enriched with agent names, model config, output size, tool usage. 11 execution log call sites now include `llmProvider`/`llmModel` in metadata. GCC metadata now records executor + LLM config at routing and completion commits. **UI fixes:** WO detail header layout (title no longer squeezed by action buttons), chat three-dot menu visibility (hover reveal + overflow fix), SplitPane gutter widened for easier drag. **Branding:** System prompt updated from FreedomForge.AI to Klear.ai / IOWA (Intelligent Work Orchestration). 227 tests across 9 test files, all passing. |
| 2026-03-19 | **Pre-Performance-Plan note captured from Claude review.** Three cautions were recorded before performance work begins: (1) PM Alpha's prompt needs a Darla clause so workflows routed through Darla have explicit scoring criteria for implementability and brand-spec fidelity; this is a prompt update, not a code change, and should land before Darla carries meaningful workflow traffic. (2) The benchmark pack must include both prompt-heavy and provider-latency-dominated runs, plus at least one multi-tool case and one Gamma/post-process case, or optimization work may target the wrong bottleneck. (3) The future execution-profile resolver must default to `safe` when unset so any environment that forgets to set a profile preserves current behavior by default. |
| 2026-03-19 | **Future provider note captured.** Long-term roadmap should preserve an integration path for locally hosted LLM providers such as LM Studio, Ollama, llama.cpp-compatible servers, or similar OpenAI-compatible local endpoints. This should work for both local and cloud app deployments where the app can reach the local/model host over a permitted network path. When provider work is revisited, prefer extending the existing provider abstraction in `server/llm-client.ts` rather than forking separate local-vs-cloud logic. |
| 2026-03-21 | **Execution Reliability Fix (GOO2 incident).** BUG-048: PocketFlow options-scope regression — `nodeExecStep()` referenced `options` from `pocketflowExecute()` closure but is a module-level function. Fix: propagate profile flags (`promptCompaction`, `batchedSynthesis`, `reviewReduction`) via SharedDict. Lifecycle normalization: retry + admin repair retry now reset `workflowExecutionId` (matching reopen behavior), mark prior execution `superseded_by_retry`. New `server/execution-strategy-resolver.ts`: deterministic workflow template matching after Tier 1 approval — additive scoring (format, category, token overlap, workflow-shaped signals, explicit agent coverage), threshold >= 8, margin >= 2. GOO2 falls back to direct execution (existing Purple GOO template uses Mark+Paul, not Hank+Darla). Double-execution guard prevents duplicate active workflows. Resolver wired into `processWorkOrder()` between Tier 1 approval and direct dispatch. 247/248 tests pass. |
| 2026-03-21 | **BUG-049: Quality review heartbeat starvation.** GOO3 confirmed BUG-048 fix works (PocketFlow executes, Hank produces HTML, quality review runs) but watchdog killed WO during quality review LLM call (103s no heartbeat). Fix: `withWorkOrderHeartbeatGuard(orderId, phase, fn, attemptId)` helper in orchestration.ts — periodic heartbeat during review callback, ownership-aware (stops if attempt invalidated), always cleared in finally. Wrapped both quality review call sites (initial + revision-loop) + explicit heartbeat before revision re-dispatch. No watchdog threshold changes. |
| 2026-03-21 | **BUG-050/051/052: Attempt integrity + watchdog correctness.** GOO4 exposed 3 issues: (1) BUG-050: zombie continuation after watchdog kill — added 3 `isAttemptStillOwner` checks at revision-loop boundaries (before re-dispatch, after PocketFlow returns, before terminal write). (2) BUG-051: watchdog kills now write `bdmMarker` + `tier2Result` with failure reason so UI shows why WO failed. (3) BUG-052: per-WO ceiling calibration — `resolveProcessingCeiling()` gives 20 min for format-heavy/multi-page/revision-eligible WOs, 10 min default. Stale-heartbeat threshold unchanged. 248/248 tests pass. |
| 2026-03-21 | **BUG-053: Progress-aware soft-timeout routing.** Split watchdog kill path: stale heartbeat → hard fail (`watchdog_stuck`); budget exceeded + fresh heartbeat → soft timeout (`watchdog_budget_exceeded`, `awaiting_operator`, best artifact preserved). Both paths invalidate the attempt (zombie protection). Design note: fresh heartbeat is an operational proxy for live progress, not a permanent semantic truth. 248/248 tests pass. |
| 2026-03-21 | **Loop 14: Checklist Semantics + PPTX Contract Flexibility + Know-How Breadcrumb Parsing.** Patch A: 2DO checklist counter split into "Milestones: X/Y" + "Events: N" — no longer shows misleading mixed ratio. Patch B: PPTX `cover` and `thank you` no longer hard-required by default in content contracts — only real content sections (executive summary, roadmap, etc.) are enforced. Patch C: Know-How retrieval now normalizes breadcrumb paths (`Workspace > X > Y` → `X/Y`) and folder lookup tries `Workspace/` prefix. BUG-050 extended: ownership check after main PocketFlow execution (not just revision loop) prevents zombie from completing WO after watchdog kill. 248/248 tests pass. |
| 2026-03-25 | **v0.9.8a — GitHub Pages Publish Pipeline.** New `server/publish.ts` — push HTML artifacts to GitHub Pages (`purpleicecube/deliverables` repo) via Contents API. Schema: `publishedSlug`, `publishedAt`, `publishedUrl`, `publishPolicy` on artifacts. API: publish, unpublish, list published, sandbox publish. Public route `GET /p/:slug`. Sandbox UI: one-click Publish/Unpublish buttons with Live link and Copy URL. BUG-053 hardened: 90s phase-level timeout via `PhaseTimeoutError` in heartbeat guard — quality review auto-approves on timeout. Know-How parser: label-colon path extraction (Phase 1), `normalizePath()` shared function, broader Phase 3 regex. WO detail: Accept and File button. Submit order: description max 65K chars. |
| 2026-03-29 | **v0.9.9 — Know-How Chat Retrieval Hardening (Session 14, Loops 15–20).** Retrospective loop normalization per LOOP_SOP.md. Loop 15 (BUG-054): parser fix — articles, bare folders, trigger regex. Loop 16 (FEAT-005): folder directory listing in retrieval. Loop 17 (FEAT-006): universal text extraction service (`server/text-extractor.ts`) — PDF/DOCX/PPTX via registry pattern, `mammoth` dep added. Loop 18 (BUG-055): name search timeout fix — `searchArtifactsByName` (name-only ILIKE), 15s→0.76s. Loop 19 (BUG-056): source-over-derivative scoring — `isWoGeneratedArtifact()` deprioritizes WO outputs across all tiers. Loop 20 (FEAT-007): `buildWorkspaceIndex()` live directory tree in Chat system prompt + 6-point workspace content rules + 15s timeout guard. Created `docs/KNOWHOW_USER_GUIDE.md`, Know-How Evolution Plan v1.0, implementation report. |
| 2026-03-29 | **Chat Anti-Hallucination Hardening (Session 15, Loops 21–24).** Operator spotted Aiden fabricating a web lookup (inventing names, citing a URL never visited) when nudged "did you check the Leadership page." Root cause: duplicated web-research logic with no evidence model — LLM could claim tool actions that never ran. **Loop 21 (FEAT-008): Centralized web-research routing.** New `server/web-research.ts` — single `resolveWebResearch()` function replaces duplicated blocks in both chat endpoints (session-based and stateless). Returns structured `WebResearchResult` with status, visited URLs, result count, context block, and status line. **Loop 22 (FEAT-009): Explicit tool-state injection.** Every chat turn now gets `=== TOOL STATE ===` with `WEB_RESEARCH_STATUS: not_run / ran / failed` plus visited URLs and result count. LLM always knows whether research actually executed. **Loop 23 (FEAT-010): Hard prompt rule tied to tool state.** New "WEB RESEARCH TOOL-STATE RULE" section in `llm-client.ts` system prompt — hard constraints per status value. `not_run` → must not claim access to external sources, must suggest URL or rephrase. `failed` → must not claim results found. `ran` with 0 results → may report search ran, must not fabricate. `ran` with results → use only data present in LIVE WEB RESEARCH section. No exceptions. **Loop 24 (FEAT-011): Conversational follow-up trigger awareness.** `detectFollowupIntent()` in web-research.ts — triggers web search when current message uses follow-up phrasing ("did you check", "look up", "verify") AND recent conversation (last 4 messages) references external entities (company, website, leadership page, etc.) or contains URLs. Verified: exact hallucination scenario now produces honest "search ran but found nothing" response. |
| 2026-03-29 | **Stitch Design Integration v1 (Session 16, Loops 25–30).** First Stitch integration path: workflow-first, external-launch, manual-sync-first, minimal-schema-first. **Loop 25 (FEAT-012): Stitch Access Surface.** New `client/src/pages/stitch-access.tsx` — Design Lab page with external launch, workflow model explainer, operator setup steps. Sidebar nav entry under Environments. Route at `/design-lab`. **Loop 26 (FEAT-013): External Step Orchestration.** `server/orchestration.ts` — `stepType === "external"` now routes to `awaiting_operator` instead of attempting agent dispatch. Parallel group exclusion for external steps. Existing 248 tests pass. **Loop 27 (FEAT-014): Stitch State Persistence.** New `POST /api/workflow-executions/:id/stitch-context` route — merges Stitch context into `workflowExecutions.context.stitch` (project URL, sync status, variant selection, notes). `StitchPanel` component in WO detail page — edit/view Stitch state, Open Stitch button. New `POST /api/workflow-executions/:id/step-runs/:stepRunId/operator-resolve` — operator-accessible step resolve (not admin-only). **Loop 28 (FEAT-015): WO Artifact Upload.** New `POST /api/work-orders/:id/artifacts/upload` — operator attaches screenshots/DESIGN.md with tags, linked via `sourceType: "work_order"`. **Loop 29 (FEAT-016): Hank Handoff + Chat Routing.** Verified: Stitch context flows to Hank via `execution.context`, preview gate uses external step routing. Added Stitch workflow routing guidance to chat system prompt. **Loop 30: Connector Seam Documentation.** Documented future integration points (adapter module, settings, UI indicator) in implementation pack — no runtime changes. |
| 2026-05-03 | **Public landing footer link to Attributions enabled (Codex).** The landing-page footer line `Attributions & Licenses` was still static text and the logged-out app flow had no real `/attributions` route. Updated `apps/console-streamlit/Home.py` to render the footer text as a same-tab link and to run the unauthenticated surface through a hidden two-page `st.navigation` router (`/` for the public landing page and `/attributions` for the public attribution register). The authenticated router also now pins the page to `url_path="attributions"` for stability, and `views/attributions.py` remains public-safe without requiring an API session. Verification: `tests/test_views_import.py` 23 passed and `tests/test_app_loads.py` 2 passed. |
| 2026-05-03 | **Attributions truth-card correction (Codex).** Replaced the `Aiden Zephyr / TIB` attribution card content with the exact operator-supplied source version: title `Aiden Zephyr & TIB`, subtitle `Thomas C. Appling III / FF.AI`, badge `Creative Attribution`, metadata labels `Contributor` / `Organization` / `Type`, revised body copy, and the pink `PRECEDENCE NOTE` panel inside `Timeline & Precedence`. Implemented in `apps/console-streamlit/views/attributions.py`. Verification remained green: `tests/test_views_import.py` 23 passed and `tests/test_app_loads.py` 2 passed. |
| 2026-05-03 | **IWO3 version bump to v1.2.3 (Codex).** Updated the canonical app version in `package.json` from `0.9.8` to `1.2.3`, aligned the Streamlit sidebar footer in `apps/console-streamlit/shell.py` to `AIDEN_IWO3 v1.2.3`, and aligned the MCP client handshake version in `server/mcp-client.ts` to `1.2.3`. This is the new local/public release identity baseline. |
| 2026-05-02 | **Loop Eta phase 1.1 corrective pass (Codex).** Fixed the post-Claude handoff gaps in the IWO3 branch: `apps/api-fastapi/runtime/tier_2_subagents.py` now supports all routed Tier 2 roles (`jamie_tier_2`, `nyx_tier_2`, `polaris_tier_2`, `darla_tier_2`, `sop_master_tier_2`) plus short aliases and fallback prompts; `apps/api-fastapi/routes/llm.py` now exposes `GET /llm/configs/{id}/tool_history`; `apps/console-streamlit/api_client.py` + `views/sub_agents.py` now render a real per-agent Tool History tab instead of the old stub. `db/seeds/llm_configs.json` corrected Darla and SOP Master from authored placeholders to real IWO2 live imports (`openrouter/google/gemini-2.5-flash` and `openrouter/qwen/qwen3-coder-next`, provenance `extracted_from_iwo2_live`). Local dev DB aligned by running `infra/local/seed-iwo3.sh`; live verification confirmed both rows now match the corrected seed. Tests after reseed: Streamlit `28 passed`; DB-backed FastAPI Eta suites `20 passed` (warnings only: pre-existing Pydantic deprecations). WS024 addendum authored at `WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_ETA_PHASE_1_1_CODEX_ADDENDUM_v0.1.0.md` — this supersedes the stale Darla/SOP provenance and Tool History stub claims in the earlier Eta phase-1 handback. |
| 2026-05-02 | **Post-close Loop Eta local follow-through (Codex).** Local runtime env activation completed for Stitch, Brave, and Perplexity by updating `/home/virgina/VS_AIDEN_IWO3/.env` with redacted local-only values and correcting `STITCH_MCP_COMMAND` quoting so shell-sourced restarts work. Live verification passed: `GET /tools/stitch_design/test_connection` returned `ok=true` with `tool_count=12`; one live Brave query succeeded; one live Perplexity query succeeded. Small UI parity pass also tightened work-order status colors to better mimic IWO2: added violet/sky shared chip variants in `apps/console-streamlit/shell.py`, refined status mapping in `views/dashboard.py`, and added semantic status/priority chips in `views/work_orders.py`. Streamlit view/import tests: `24 passed`. Durable WS024 notes: `WS024_IWO3[Branch]/05_Artifacts/loop_eta_review_packet/IWO3_LOOP_ETA_POST_CLOSE_ENV_ACTIVATION_NOTE_v0.1.0.md` and `.../IWO3_LOOP_ETA_POST_CLOSE_STATUS_UI_NOTE_v0.1.0.md`. |
| 2026-05-02 | **Hosted ζ.6 bootstrap fix (Codex).** `infra/local/seed_user_passwords.py` was upgraded so hosted rollout no longer assumes pre-existing `users` rows. The helper now supports both existing-user password seeding and direct creation of new hosted login users plus `client_memberships`, then hashes/stores their passwords in one interactive flow. This corrects the mismatch between `IWO3_SEED_SCOPE=reference` (which skips `users`/`client_memberships`) and the previous hosted runbook language. |
| 2026-05-02 | **Hosted Railway parity execution completed (Codex).** Railway CLI was installed locally and authenticated against the `iwo3` project. Hosted Railway env was synced to the local provider/tool posture (`IWO3_AUTH_MODE`, JWT key, crypto master key, Groq/OpenRouter/Gamma/Stitch/Brave/Perplexity), and `iwo3-api` redeployed successfully on commit `b7a399a`. The hosted Postgres was discovered to be partially initialized rather than blank, so instead of replaying from `0000`, a targeted reconciliation applied the missing late migrations `0012`, `0019`, `0020`, `0021`, and `0022`. Reference seed was then run against Railway Postgres, followed by a one-time hosted parity repair that backfilled `llm_config_versions` to 12 rows and `sub_agent_tools` to 30 rows (the current reference scope intentionally leaves assignments empty). Hosted JWT login was enabled in practice by setting password hashes for seeded Klear owner/admin/operator users from a local-only secret file under `VS_PDOE/+8PGITHUB/00_Secrets/`; verification passed (`POST /auth/login` returned 200 with access + refresh tokens). Klear Gamma adapter activation was written into `adapter_credentials` with `first_invocation_confirmed_at`, and live Railway verification passed: `/healthz` 200, `/tool_catalog?runtime_status=runnable` returned 13 rows with bearer auth, `/tools/stitch_design/test_connection` returned `ok=true`, `tool_count=12`, `command_resolved=true`. The only remaining public-facing gap is Streamlit Cloud dashboard-side: `https://iwo3.streamlit.app` exists but currently redirects through Streamlit auth, so repo/branch/API-base-url/visibility still need a manual dashboard confirmation. Durable governance note: `WS024_IWO3[Branch]/05_Artifacts/loop_eta_review_packet/IWO3_LOOP_ETA_HOSTED_PARITY_EXECUTION_NOTE_v0.1.0.md`. |
| 2026-05-02 | **Work Orders Lifecycle footer sizing bugfix (Codex).** The footer summary at the bottom of the Work Orders Lifecycle tab was using default Streamlit `st.metric` widgets, which rendered the role/output/provider/token values at oversized KPI scale and looked visually inconsistent with the rest of the console. Replaced those four metrics with a compact custom stat strip in `apps/console-streamlit/views/work_orders.py` and added the shared CSS in `apps/console-streamlit/shell.py`. Verification on the touched Streamlit surface: `tests/test_views_import.py` 22 passed and `tests/test_app_loads.py` 2 passed. Durable packet note updated in `WS024_IWO3[Branch]/05_Artifacts/loop_eta_review_packet/IWO3_LOOP_ETA_POST_CLOSE_STATUS_UI_NOTE_v0.1.0.md`. |
| 2026-05-02 | **Attributions page added to IWO3 (Codex).** Added `apps/console-streamlit/views/attributions.py` and linked it from the `Architecture` sidebar group in `Home.py`. The new page is a document-style attribution register modeled on the IWO2 reference rather than an admin/settings view: back control, large register title, collected date, bordered cards, metadata grid, and narrative sections for `Creator & Origin`, `Core Concept`, `Timeline & Lineage`, `License Notice`, and `Attribution Statement`. First release seeds foundational lineage plus major runtime-tool entries: AgentGoPro/AgentGoFlow, LuaAzullaB Orchestration Framework, Aiden Zephyr/TIB, PocketFlow, GCC Memory, Gamma, Stitch MCP, Brave Search API, and Perplexity API. Verification on the touched Streamlit surface: `tests/test_views_import.py` 22 passed and `tests/test_app_loads.py` 2 passed. Durable packet note: `WS024_IWO3[Branch]/05_Artifacts/loop_eta_review_packet/IWO3_LOOP_ETA_POST_CLOSE_ATTRIBUTIONS_NOTE_v0.1.0.md`. |
| 2026-05-02 | **Hosted navigation hardening for brand/Dashboard/Attributions (Codex).** Fixed three small but related Streamlit routing issues after hosted review. In `apps/console-streamlit/shell.py`, the top-right `Dashboard` return control had been hardcoded to `/Dashboard`; it now routes to the default-page root `/`, which matches Streamlit Cloud's `st.navigation` behavior. The sidebar brand block is now clickable and routes to `/` in the same tab. In `apps/console-streamlit/views/attributions.py`, the page now ends with a plain trailing `main()` like the rest of the Streamlit views instead of `if __name__ == "__main__": main()`, so it executes correctly under `st.navigation`. Added `attributions.py` to `tests/test_views_import.py`. Verification: `tests/test_views_import.py` 23 passed and `tests/test_app_loads.py` 2 passed. Durable packet note updated in `WS024_IWO3[Branch]/05_Artifacts/loop_eta_review_packet/IWO3_LOOP_ETA_POST_CLOSE_ATTRIBUTIONS_NOTE_v0.1.0.md`. |
| 2026-05-02 | **Brand icon source unified (Codex).** The sidebar brand mark did not visually match the actual IWO3 icon asset. Updated `apps/console-streamlit/shell.py` and `Home.py` so both the authenticated sidebar brand and the public landing-page brand render the shared `apps/console-streamlit/assets/favicon.png` through a cached base64 image helper, replacing the older inline SVG mark. This aligns the in-app brand icon with the favicon/browser icon and removes divergence between the two surfaces. Verification: `tests/test_views_import.py` 23 passed and `tests/test_app_loads.py` 2 passed. |
| 2026-05-16 | **Platform version bump — IWO3 v1.2.3 → v1.5.1 + Aiden Alpha v3.0.6 → v4.0.1 (operator decision, applied across all surfaces).** Canonical platform identity is now `AIDEN_IWO3 v1.5.1`; canonical agent-spec lineage in the IWO3 runtime is now `Aiden Alpha v4.0.1` (jumping from the v3.x branch to align with the TIB v4.x spec lineage per the AIDEN ALPHAv3 → IWO → TIB-as-future-IWO-branch convergence). Code surfaces updated: `/home/virgina/VS_AIDEN_IWO3/package.json` (`1.2.3` → `1.5.1`); `apps/console-streamlit/shell.py` sidebar footer (`AIDEN_IWO3 v1.2.3` → `v1.5.1`); `server/mcp-client.ts` MCP handshake (`1.2.3` → `1.5.1`); `apps/api-fastapi/routes/health.py` `/healthz` response `version` field (scaffold marker `0.0.1` → tracking app version `1.5.1`, with comment locking it to package.json in lockstep going forward). Persona surfaces: `apps/api-fastapi/runtime/tier_1_aiden.py` `AIDEN_SYSTEM_PROMPT` now opens with `"You are Aiden (Aiden Alpha v4.0.1) running on AIDEN_IWO3 Platform v1.5.1 ..."` so Aiden self-identifies correctly to operators; Klear's seeded `aiden_tier_1.system_prompt` had stale IWO2-era refs (`IWO Platform v0.3.8 / Aiden Alpha v0.6.9`, `Platform: IWO v0.8.9 (B+ Hardened`) refreshed to `IWO3 Platform v1.5.1 / Aiden Alpha v4.0.1` and `Platform: IWO3 v1.5.1 (Hardened` — applied to both `db/seeds/llm_configs.json` and the live Klear row. FFAI's `aiden_tier_1.system_prompt` is NULL post-BUG-069 so it inherits the runtime default's self-id automatically. Verification: `/healthz` returns `version: "1.5.1"`; 19/19 affected pytest + 27/27 Streamlit view-import smokes green; no test pins specific version strings other than the bumped ones. **What is intentionally NOT touched**: historical session notes / completed-loop records / test fixtures that reference `v1.2.3` — those are historical state markers, not current state; the regex test that uses `"v1.2.3"` as a literal example (intent_parser rejection case) also stays. Durable governance note: this row + WS024 CLAUDE.md mirror row. |
