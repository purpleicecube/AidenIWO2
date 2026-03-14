# CLAUDE.md — AIDEN_IWO

## Overview

AIDEN_IWO (Intelligent Work Orchestration) is a 2-tier AI agent platform. Tier 1 (Aiden) is the orchestrator/policy engine. Tier 2 (sub-agents) execute work orders via PocketFlow. Built on Express 5 + React 18 + PostgreSQL + Drizzle ORM.

### Product Lineage

Both AIDEN_IWO and AIDEN_TIB derive from the base **AIDEN_ALPHAv3** prompt specification. IWO is the full-stack runtime platform (this repo). TIB (The Internal Brain) is the spec-level agent architecture (sub-agent definitions, BDM routing, delegation protocols). TIB will become a **specialized branch** of a future IWO version — it is not a separate product. IWO is the broader, more versatile platform.

- **Version:** v0.9.5 (alpha)
- **Repo:** `purpleicecube/AidenIWO-or-TIB` (branch: `main`)
- **Local path:** `/home/virgina/VS_AIDEN`
- **Related workspace:** `VS_PDOE/WS006_AIDEN(TIB)`
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
| `ROADMAP_FEATURES.md` | Full features inventory and roadmap (123 features, 16 domains) |

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
| 2026-03-04/05 | Fixed 6 additional bugs (BUG-005 through BUG-010): Tier 1 Zod validation failure (resilient parsing with defaults), ESM `__dirname` polyfill for post-processing, quality review truncation fix (postProcessedFile param), PPTX filing routing to #Documents, workspace preview base64 gibberish (smart file category rendering with 4 modes), download endpoint for all binary types. New features: PPTX post-processing pipeline (md-to-pptx.py), smart file preview/download for all file types, skills content injection into Tier 2 prompts, password-based auth (bcryptjs). Created ROADMAP_FEATURES.md (123 features across 16 domains). Updated BUGFIX_LOG.md, CHANGELOG.md (v0.3.8). |
| 2026-03-07 | Session 7. BUG-021: PDF artifact never generated — built end-to-end PDF pipeline (pandoc md→HTML + Playwright Chromium HTML→PDF). BUG-022: PDF layout broken with LibreOffice — switched renderer to Playwright Chromium (`server/scripts/html-to-pdf.cjs`); reworked `injectPdfStyles` for full-bleed header/footer, full-width content, pandoc body override, fixed-position footer. PDF output: 1-page professional layout, edge-to-edge dark navy header/footer. BDM evaluator fix: `llmEvaluate` now receives `platformFormat` to suppress binary-file demand for PDF/PPTX orders. Deliverable deduplication: `nodeBuildResponse` uses only last iteration output for PDF. Deliverable path UI: `GET /api/artifacts?sourceId=`, `DeliverableCard` component, `FileDown` indicator on work orders list. BUG-025: Content duplicated after multi-iteration refine loop — `nodeBuildResponse` general path now uses last iteration's step outputs only (same as PDF path). ADR-001 filed: full `delta_overlay` architecture deferred to v0.5+. PocketFlow tuning: maxIterations=9, convergenceThreshold=0.75, maxAutoRevisions=4. App renamed AIDEN_IWO2 in sidebar/landing/footer. 25 total bugs fixed. |
| 2026-03-14 | **v0.9.4 — HITL Candidate Review + Three-Level Template Precedence.** `gammaDeliveryPolicy` on `workflow_templates` (auto_revise/candidate_review). WO-level `gammaTemplateKey` override on `work_orders` (highest precedence). Candidate columns on `gamma_generation_records`: `candidateStatus`, `candidateGroup`, `artifactFiledPath`, `selectedAt`, `selectedBy`. Durable candidate persistence in `.local/gamma_candidates/{woId}/`. Orchestration gate in `orchestration.ts`: when `gammaDeliveryPolicy=candidate_review`, WO moves to `awaiting_operator` after revision loop. 6 candidate API endpoints: list/select/reject/reject-all/request-more/download. Three-level template precedence: WO > workflow > global. `gammaDeliveryPolicy` passed through Tier2Result. Storage: `getGammaGenerationRecord`, `getGammaCandidates`, `selectGammaCandidate`, `rejectGammaCandidate`, `rejectAllGammaCandidates`. |
| 2026-03-14 | **Gamma PPTX integration + Template Registry.** Added `server/gamma-client.ts` (direct REST API to `public-api.gamma.app/v1.0`). New `gamma_settings` table for global config. Added `pptx_engine`, `gamma_theme_id`, `gamma_template_id` columns to `workflow_templates` for per-template Gamma routing. Klear.ai Gamma template `g_onfwfqpb52zcws3` (PPTX) and `g_122ahx4j0eer8lz` (PDF) configured. **Gamma Template Registry:** New `gamma_template_registry` table (templateKey, gammaId, contentContract, mode, status) + `gamma_generation_records` audit table. Three-layer model: Gamma template controls look, content contract controls fit, LLM prompt implements contract. Format-aware early resolution in `pocketflowExecute()` — detects PPTX/PDF format, resolves templateKey through registry, auto-swaps to format-matched entry. `gammaPolicy` on SharedDict carries resolved policy through entire execution. Content contract injected into `llmPlanSteps()` + `llmExecStep()` via `designContext`. Both PPTX and PDF `nodePostProcess()` blocks use `dict.gammaPolicy` with generation record writes + locked template enforcement. Registry API: GET/POST `/api/gamma-templates`, GET `/api/gamma-templates/:key`, PUT `/api/gamma-templates/:id`, GET `/api/gamma-generations?workOrderId=X`. Seeded `klear_live_v1` (PPTX, template_locked) and `klear_pdf_v1` (PDF, template_locked). EVAL created at `VS_PDOE/WS006_AIDEN(TIB)/05_Artifacts/EVAL_GAMMA_REGISTRY_v1.0.md`. |
| 2026-03-13 | **v0.9.2 release.** PPTX workflow readiness: replaced PPTX skill with IWO2-native md-to-pptx spec, updated TOM/PM Alpha/Mark/Paul system prompts via API for workflow orchestration. 2DO Checklist feature: `checklist_items` table + 4 endpoints + 11 lifecycle hooks + UI panel. Contract drift fix (CODEX 5.4): workflow PM completion now writes to `tier2Result` (not legacy `result`/`deliverableType` fields), synthetic WorkOrder/Tier1Result aligned to actual schema, `toolsUsed` added to Tier2Result type, `gccMemory` exposed in insert schema. 17 TS errors resolved, 50/50 tests pass. |
