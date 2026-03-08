# CLAUDE.md — AIDEN_IWO

## Overview

AIDEN_IWO (Intelligent Work Orchestration) is a 2-tier AI agent platform. Tier 1 (Aiden) is the orchestrator/policy engine. Tier 2 (sub-agents) execute work orders via PocketFlow. Built on Express 5 + React 18 + PostgreSQL + Drizzle ORM.

### Product Lineage

Both AIDEN_IWO and AIDEN_TIB derive from the base **AIDEN_ALPHAv3** prompt specification. IWO is the full-stack runtime platform (this repo). TIB (The Internal Brain) is the spec-level agent architecture (sub-agent definitions, BDM routing, delegation protocols). TIB will become a **specialized branch** of a future IWO version — it is not a separate product. IWO is the broader, more versatile platform.

- **Version:** v0.3.8 (alpha)
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
