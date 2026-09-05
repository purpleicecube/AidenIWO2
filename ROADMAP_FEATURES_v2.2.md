# AIDEN IWO — Features Inventory & Roadmap

> **Version:** 2.4
> **Last Updated:** 2026-09-05
> **Maintainer:** Darrel Vaughn

---

## Status Legend

| Tag | Meaning |
| --- | --- |
| `[SHIPPED]` | Fully operational in production |
| `[RECENT]` | Shipped in March 2026 development session |
| `[IN DEV]` | Code exists, partially working or incomplete |
| `[PLANNED]` | Approved for development, not yet started |
| `[ROADMAP]` | Future consideration, not yet scoped |

---

## 1. Platform Overview

**AIDEN IWO** (Intelligent Work Orchestration) is a full-stack platform that receives work orders from operators, evaluates them through an AI policy gate (Tier 1 — Aiden), routes approved orders to specialized sub-agents for execution (Tier 2 — PocketFlow engine), and delivers completed artifacts back through a governed approval and filing pipeline.

### Product Lineage

Both AIDEN_IWO and AIDEN_TIB derive from the base **AIDEN_ALPHAv3** prompt specification:

| Product | Description | Status |
| --- | --- | --- |
| **AIDEN_ALPHAv3** | Base agent prompt spec (v1.x through v3.0.x) | Foundation |
| **AIDEN_IWO** | Full-stack runtime platform (this repo) — the broader, more versatile project | App v0.9.5 / Prompt spec v0.4.1 (alpha) |
| **AIDEN_TIB** | Spec-level agent architecture (sub-agent definitions, BDM routing, delegation protocols) | Will become a specialized branch of a future IWO version |

TIB is not a separate product line — it will be absorbed into IWO as a specialized branch/mode in a future release.

### Tech Stack

- **Backend:** Express 5, TypeScript 5.6, Node.js 20
- **Frontend:** React 18, Vite 7, TanStack Query 5, Tailwind CSS, shadcn/ui
- **Database:** PostgreSQL 16, Drizzle ORM 0.39
- **LLM Providers:** Groq, OpenRouter, OpenAI, Anthropic
- **Post-Processing:** python-pptx, pandoc, **Playwright Chromium** (HTML→PDF), LibreOffice (→ OnlyOffice migration planned, timeline TBD)
- **Auth:** Passport + bcryptjs, connect-pg-simple sessions

### Architecture

```text
Operator → Submit Work Order
               ↓
        [ Tier 1: Aiden Policy Gate ]  ← Groq LLM (~0.8s)
               ↓ approved
        [ Tier 2: PocketFlow Engine ]  ← OpenRouter/Gemini (5-23s/call)
          Plan → Execute → Evaluate → Refine (loop)
               ↓ converged
        [ Quality Review ]  ← Aiden scores deliverable
               ↓ passed
        [ Post-Processing ]  ← md-to-pptx, format conversion
               ↓
        [ Workspace Filing ]  ← Auto-route to #Documents / #Code_Blocks
               ↓
        Operator reviews → Accept / Revise
```

---

## 2. Features Inventory

### A. Work Order Management

| Feature | Status |
| --- | --- |
| Work order CRUD (create, list, get, update) | `[SHIPPED]` |
| Status lifecycle (pending, processing, completed, failed, blocked, deferred, awaiting_operator, archived) | `[SHIPPED]` |
| Priority levels (low, medium, high, critical) | `[SHIPPED]` |
| Type classification and routing | `[SHIPPED]` |
| BDM (Business Decision Markers) for human intervention points | `[SHIPPED]` |
| Archive, reopen, retry, kill, defer operations | `[SHIPPED]` |
| Correlation ID tracking for GCC memory | `[SHIPPED]` |
| Submission tracking (submittedBy, createdAt, updatedAt) | `[SHIPPED]` |
| Work order templates (save/reuse common requests) | `[PLANNED]` |
| **2DO Work Order Checklist** — Living checklist auto-created at work order submission. Managed by Aiden (Tier 1) or the assigned PM sub-agent as appropriate. Tracks one-liner status items through the full processing lifecycle (Tier 1 gate, Tier 2 execution, quality review, filing). Persists across iterations — when a work order is reopened, retried, or revised, the checklist continues with new entries appended. Provides at-a-glance running summary of where the order stands without reading full execution logs. | `[PLANNED]` |
| Scheduled work orders (cron-based, using scheduleRules field) | `[ROADMAP]` |

### B. Tier 1 — Aiden Policy Gate

| Feature | Status |
| --- | --- |
| LLM evaluation and routing (approve/reject/defer) | `[SHIPPED]` |
| Resilient JSON parsing with flexible field mapping and defaults | `[RECENT]` |
| Debug logging for LLM responses | `[RECENT]` |
| Quality review system (multi-criteria scoring, revision recommendations) | `[SHIPPED]` |
| Quality review post-processing awareness (detects generated .pptx/.docx) | `[RECENT]` |
| System prompt v0.4.0 — major uplift: correct progression order (Identity → Architecture → GCC Authority → Platform Constraints → 5-Phase Cycle → Guardrails → Output → Stance), Tier 1.5 Workflow PM added to architecture, GCC authority runtime-enforcement notes, Memory Advisor (P1.4) spec, PPTX pipeline routing, rate limit awareness in PHASE 2, smart file preview in PHASE 5, artifact_type in JSON schema | `[RECENT]` |
| Multi-model routing (auto-select best LLM per task type) | `[ROADMAP]` |

| Open web search from chat (Brave / Perplexity / DuckDuckGo / scrape) with mandatory-search rubric for outside-world questions | `[RECENT]` |
| Search provenance in chat — tool used, query issued, clickable sources | `[RECENT]` |
| Platform-honesty rules — no claimed action without a tool result, no constructed platform URLs, explicit "I cannot" | `[RECENT]` |
| Grounding preamble scoped so closed-world sourcing does not forbid fetching a new source | `[RECENT]` |
| Chat history treated as a record of what was said, not a source of verified fact | `[RECENT]` |

### C. Tier 2 — PocketFlow Execution Engine

| Feature | Status |
| --- | --- |
| Plan → Execute → Evaluate → Refine iterative loop | `[SHIPPED]` |
| Parallel step execution for independent steps | `[SHIPPED]` |
| Sequential execution for dependent steps | `[SHIPPED]` |
| Convergence scoring (threshold 0.8, max 3 iterations) | `[SHIPPED]` |
| Timeout handling per step (default 30s) | `[SHIPPED]` |
| Retry policies (max retries, delay) | `[SHIPPED]` |
| Intermediate output filtering (removes planning metadata, JSON fragments) | `[SHIPPED]` |
| PPTX post-processing pipeline (md-to-pptx.py via python-pptx) | `[RECENT]` |
| PDF post-processing pipeline — pandoc (md→HTML) + **Playwright Chromium** (HTML→PDF). Full CSS support: `@page { margin: 0 }`, `position: fixed`, full-bleed header/footer. Keyword detection ("pdf") takes priority over skill-based routing. PDF stored in `.local/workspace/05_Artifacts/`, registered in DB as artifact on work order completion. Professional layout: edge-to-edge dark navy header + pinned footer, typography overrides defeating pandoc's default narrow body. | `[RECENT]` |
| ESM-compatible __dirname polyfill for script execution | `[RECENT]` |
| **Done Contract** — deterministic closeout evaluator with 4 artifact tracks (Static Web Page, Software Artifact, Document, PPTX). Governed HITL "Wrap It Up" override. Gate in `completeAndFileWorkOrder()`. | `[RECENT]` |
| **PPTX preflight validator** — blocks empty, JSON, placeholder, unsegmented content before Gamma. Contract parser extracts slide range + required sections. | `[RECENT]` |
| **PPTX slide source shaper** — restructures flat LLM output into clean slide-segmented markdown before Gamma. Deduplication, bullet trimming, slide cap. | `[RECENT]` |
| **Post-Gamma compliance checker** — verifies file existence, size, MIME, estimated slide count vs contract. | `[RECENT]` |
| **PPTX review supplement** — injects preflight/compliance/contract evidence into Aiden quality review so LLM can reject weak slide-source even when binary exists. | `[RECENT]` |
| **Workflow PPTX post-processing** — safety net runs Gamma/local conversion on PM-assembled work product when no step produced a binary. | `[RECENT]` |
| **Local PPTX fallback reclassified** — explicitly labeled "draft quality — not Gamma-branded" in logs, checklist, and finalMessage. | `[RECENT]` |
| **Gamma heartbeat** — `onHeartbeat` callback in polling loop prevents watchdog from killing active Gamma generation (60-150s). | `[RECENT]` |
| **Machine-local path portability** — scripts use `SKILLS_DIR`/`PLAYWRIGHT_PATH` env vars with local fallback. | `[RECENT]` |
| Tool executor integration with PocketFlow steps | `[IN DEV]` |

### D. Sub-Agent System

| Feature | Status |
| --- | --- |
| Sub-agent CRUD (name, type, description, capabilities) | `[SHIPPED]` |
| LLM configuration per agent (provider, model, base URL, system prompt) | `[SHIPPED]` |
| Tool assignments via junction table | `[SHIPPED]` |
| Control modes: "aiden" (Tier 1 controlled) or "independent" (operator controlled) | `[SHIPPED]` |
| Agent status tracking (active, inactive) | `[SHIPPED]` |
| Tool usage history per agent | `[SHIPPED]` |
| LLM connection testing per agent | `[SHIPPED]` |
| **Mark** — Marketing/creative specialist sub-agent. Handles brand content, PDFs, presentations, visual assets. Prompt includes AUTHORIZATION RULES (AIDEN > PM > Operator priority), WORKFLOW EXECUTION RULES (step-by-step reporting, evidence-only completion claims), and TOOL ORCHESTRATION AUTHORITY (mode-aware tool request/provisioning protocol). | `[RECENT]` |
| Sub-agent AUTHORIZATION RULES — AIDEN/PM/Operator priority hierarchy with conflict pause-and-escalate | `[RECENT]` |
| Sub-agent TOOL ORCHESTRATION AUTHORITY — mode-aware tool request protocol (Manual/Semi-Autonomous/Autonomous paths), provisioning authority chain, evidence truthfulness requirement | `[RECENT]` |
| Sub-agent execution mode awareness — `getToolsForStep` reads `operational_settings.current_mode`; skill auto-import runs only in semi_autonomous/autonomous; manual mode skips auto-import and enforces explicit tool assignment only | `[SHIPPED]` |
| Sub-agent "Tool Needed" signal parsing — `handleToolNeededSignal` in `orchestration.ts` detects `**Tool Needed**: [name]` blocks in step output; auto-provisions matching skill and retries step in semi/autonomous mode; surfaces HITL block in manual mode | `[SHIPPED]` |
| Mark sub-agent — B04_MKTG persona addendum integrated (IDENTITY, CORE OPERATING STYLE, SIGNATURE STRENGTHS ×5, LEADERSHIP BEHAVIOR, PREFERRED DELIVERABLES, HARD BOUNDARIES, TONE) combined with full CODEX governance blocks | `[SHIPPED]` |

| Sub-agent model picker driven by the live provider catalogue (Groq / OpenRouter) | `[RECENT]` |
| Provider model-catalogue TTL cache (6h default, `?refresh=true` bypass, stale-on-failure fallback) | `[RECENT]` |
| Advisory chat-capability classification — hides speech / embedding / classifier models behind "show all" | `[RECENT]` |
| Current-model preservation — a retired or filtered model stays selectable and flagged, never silently re-pointed | `[RECENT]` |
| Provider ↔ credential cross-wire guard on every `llm_configs` write path (create / update / rollback / seed) | `[RECENT]` |
| Model connection test per sub-agent (`POST /llm/test`) | `[SHIPPED]` |
| Per-config version history + rollback | `[SHIPPED]` |

### E. GCC Memory (Global Context Commits)

| Feature | Status |
| --- | --- |
| JSONB storage in work_orders.gccMemory | `[SHIPPED]` |
| Breadcrumb trails (last 50 actions) | `[SHIPPED]` |
| Commit index with timestamps, summaries, tags | `[SHIPPED]` |
| Execution logs (last 200 entries) | `[SHIPPED]` |
| Metadata tracking (status, last_commit, custom fields) | `[SHIPPED]` |
| Project ID generation from correlation ID | `[SHIPPED]` |
| Per-session GCC memory endpoint | `[SHIPPED]` |

### F. Workspace & Artifact Management

| Feature | Status |
| --- | --- |
| Folder tree (10 default folders: 00_Planning through 06_Tests, #Documents, #Images, #Code_Blocks) | `[SHIPPED]` |
| Artifact storage with versioning (name, type, mimeType, size, content) | `[SHIPPED]` |
| Auto-filing deliverables to correct folder based on content analysis | `[SHIPPED]` |
| Binary file routing — .pptx, .docx, .pdf always filed to #Documents | `[RECENT]` |
| Smart file preview — 4 rendering modes (binary download, image inline, HTML iframe, text pre) | `[RECENT]` |
| Download support for all file types (.pptx, .docx, .xlsx, .pdf, .zip, .gz, images) | `[RECENT]` |
| File type icons and human-readable labels for 20+ MIME types | `[RECENT]` |
| Image uploads with placeholder IDs | `[SHIPPED]` |
| Re-filing support after work order revision | `[SHIPPED]` |
| **Workspace Context Documents** — Operator-created project folders with designated reference documents. On work order submission, the system pulls designated docs from a folder and injects them into the work order context for Tier 2 execution. Includes constraints: max doc count per order, max file size per doc, total context budget, supported formats (.md, .docx, .pdf, .txt, .xlsx). UI: folder picker in submit-order form, document selector with preview, context size indicator. | `[PLANNED]` |
| **Desktop File Upload to Workspace** — Operator can upload files from their local desktop directly into a designated workspace folder. Backend: `POST /api/workspace/upload` accepts JSON `{name, mimeType, data, folderId}`; stores text files as UTF-8, binaries as base64; 10MB max. Supported formats: .md, .txt, .html, .css, .js, .ts, .json, .pdf, .docx, .pptx, .xlsx, images (PNG/JPEG/GIF/WebP/SVG). UI: "Upload File" item in the New dropdown (file picker) + drag-from-desktop drop zone overlay on the file grid, scoped to the currently open folder. Supports multi-file drop. | `[RECENT]` |

| Auto-filing to `Outputs/<YYYY-MM-DD>/<order-slug>_<id8>/` (IWO2 shape restored) | `[RECENT]` |
| Operator-directed filing override — "put this in a folder called X" | `[IN DEV]` — parameter plumbed and honoured, no caller passes it yet (CR-020) |
| Aiden workspace tools — `workspace_create_folder`, `workspace_list_tree`, `workspace_locate_output` | `[RECENT]` |
| Deep link to a document (`/workspace?file=<artifact_id>`) | `[RECENT]` |
| Rendered markdown preview with raw-source toggle | `[RECENT]` |
| Download as `.md` and self-contained `.html` | `[RECENT]` |
| Artifact → work order linkage (`workOrderId` in artifact metadata) | `[RECENT]` |
| Download as PDF / DOCX from the workspace viewer | `[PLANNED]` — blocked on CR-013 (`sandbox_docx` / `sandbox_pdf` stubs); PDF available today via Render Gamma |
| Folder rename / move / delete from Aiden | `[ROADMAP]` — deliberately excluded from the first tool set; destructive actions stay human |

### G. Skills System

| Feature | Status |
| --- | --- |
| 16 skill categories in .local/skills/ (pptx, docx, pdf, xlsx, brand-guidelines, canvas-design, etc.) | `[SHIPPED]` |
| Skill import from tools (locker integration) | `[SHIPPED]` |
| Skill content injection into Tier 2 system prompts (prompt_injection tools) | `[RECENT]` |
| Available skills list endpoint | `[SHIPPED]` |
| Skill auto-discovery and recommendation — keyword-match step descriptions to .local/skills/, auto-import into Tool Locker, assign to step toolIds at creation and execution time | `[SHIPPED]` |
| Plugin marketplace for skills | `[ROADMAP]` |

### H. Workflow Templates & Orchestration

| Feature | Status |
| --- | --- |
| Workflow template CRUD (multi-step definitions) | `[SHIPPED]` |
| Step configuration (order, dependencies, retry policy, timeout) | `[SHIPPED]` |
| Execution instances with goal, context, final work product | `[SHIPPED]` |
| Per-step run tracking (status, input/output, tools used) | `[SHIPPED]` |
| Step operations (advance, skip, retry, resolve) | `[SHIPPED]` |
| Workflow PM sub-agent orchestration (review, revise, assemble, escalate) | `[IN DEV]` |
| **2DO Workflow Checklist** — Meta-checklist managed by Aiden (Tier 1) or the assigned PM sub-agent as appropriate. Aggregates the status of each constituent Work Order's 2DO list as input. Operates at workflow scope — each workflow step's WO 2DO feeds into the Workflow 2DO, giving an at-a-glance roll-up of multi-step progress. Persists across workflow restarts and step retries. No duplication — the Workflow 2DO reads from WO-level 2DOs rather than maintaining its own parallel tracking. | `[PLANNED]` |
| **Child Linked Work Orders for Workflow Steps** — Optional enterprise workflow model where selected workflow steps become first-class child Work Orders under a parent workflow or parent Work Order, instead of remaining internal `workflow_step_runs` only. Benefits: independent ownership, SLA and approval state, queueing, retry/reopen per child step, stronger departmental handoffs, and direct reuse of WO-level audit trail, 2DO, and filing logic. Tradeoff: materially higher state, UI, and synchronization complexity, so this should remain an opt-in architecture for complex enterprise workflows rather than the default workflow model. | `[ROADMAP]` |

### I. Tools & Locker System

| Feature | Status |
| --- | --- |
| Tool registration (name, type, description, endpoint, documentation) | `[SHIPPED]` |
| Semantic tagging and tag hierarchy | `[SHIPPED]` |
| Tool checkout/return/expire lease management | `[SHIPPED]` |
| Full audit trail per tool usage | `[SHIPPED]` |
| API key management (create, revoke, update) | `[SHIPPED]` |
| Tool restriction/unrestriction controls | `[SHIPPED]` |
| MCP tool listing and connection testing | `[IN DEV]` |
| External MCP server connections | `[ROADMAP]` |
| API key auto-rotation | `[ROADMAP]` |

### J. Chat & Conversational Interface

| Feature | Status |
| --- | --- |
| Chat sessions with message history | `[SHIPPED]` |
| Chat groups/projects for organization | `[SHIPPED]` |
| Interactive Aiden assistant (chatWithAiden) | `[SHIPPED]` |
| Work order extraction from conversation context | `[SHIPPED]` |
| Bulk session operations | `[SHIPPED]` |
| CHAT ACTION PROTOCOL — Aiden emits hidden action blocks from chat to trigger real platform actions (CREATE_WORK_ORDER, EXECUTE_WORKFLOW) | `[SHIPPED]` |
| Chat-driven work order creation with 3-tier extraction pipeline (action block, regex fallback, LLM extraction) | `[SHIPPED]` |
| Chat-driven workflow creation — EXECUTE_WORKFLOW action block creates template, steps, and starts PM execution in one shot | `[SHIPPED]` |
| EXECUTE_WORKFLOW JSON sanitization — strips LLM-hallucinated trailing braces before parse; action block always stripped from reply even on parse failure | `[SHIPPED]` |

### K. Sandbox Sessions

| Feature | Status |
| --- | --- |
| Create isolated execution contexts | `[IN DEV]` |
| Code/script execution in sandbox | `[IN DEV]` |
| Preview rendering with re-render support | `[IN DEV]` |
| Status tracking (pending, running, completed, failed) | `[IN DEV]` |

### L. Authentication & RBAC

| Feature | Status |
| --- | --- |
| Password-based login (bcryptjs hashing) | `[RECENT]` |
| Backup admin account (`darrel.vaughn@gmail.com`) | `[RECENT]` |
| Role-based access control (admin, operator, viewer) | `[SHIPPED]` |
| Session management (connect-pg-simple, PostgreSQL-backed) | `[SHIPPED]` |
| Admin user management panel (list, update roles, delete) | `[SHIPPED]` |
| Role-based middleware on all protected endpoints | `[SHIPPED]` |
| Email invites via SendGrid | `[IN DEV]` |
| SSO / OAuth2 provider support | `[ROADMAP]` |

### M. Approval System

| Feature | Status |
| --- | --- |
| BDM-triggered approval requests | `[SHIPPED]` |
| Approval states (pending, approved, rejected) | `[SHIPPED]` |
| Impact scoring | `[SHIPPED]` |
| Aiden recommendations with rationale | `[SHIPPED]` |
| Operator decision tracking (decidedBy, decidedAt, rationale) | `[SHIPPED]` |
| Execution mode tied to approval status | `[SHIPPED]` |
| Approval delegation chains | `[ROADMAP]` |

### N. Operational Settings & Governance

| Feature | Status |
| --- | --- |
| Execution modes (autonomous, semi-autonomous, manual-review) | `[SHIPPED]` |
| Operational settings seeded with `semi_autonomous` default | `[RECENT]` |
| Financial and risk thresholds | `[SHIPPED]` |
| Schedule rules configuration | `[SHIPPED]` |
| Emergency override (enabled flag + trigger categories) | `[SHIPPED]` |
| Execution mode plumbed into sub-agent tool provisioning decisions | `[PLANNED]` |
| Emergency triggers: security_breach, legal_deadline_24h, revenue_loss, system_outage | `[SHIPPED]` |

### O. Monitoring & Observability

| Feature | Status |
| --- | --- |
| System health endpoint (/api/health) — truthful DB/LLM/Gamma/session checks | `[RECENT]` |
| Execution logging with tier, action, message, metadata | `[SHIPPED]` |
| System health UI page (service status, uptime, DB health, Gamma, LLM, session) | `[RECENT]` |
| GCC commit history per work order | `[SHIPPED]` |
| Tool audit logs with timestamps and actor tracking | `[SHIPPED]` |
| Unified version/build identity from package.json (no hardcoded versions) | `[RECENT]` |
| Startup env validation — hard-blocks on missing critical env vars | `[RECENT]` |
| Execution logs include LLM provider/model metadata at all agent-referencing call sites | `[RECENT]` |
| GCC metadata records executor + LLM config at routing and completion commits | `[RECENT]` |
| 2DO checklist enriched with agent names, model config, output size, tool usage | `[RECENT]` |
| Audit dashboard (visual log explorer) | `[ROADMAP]` |
| WebSocket real-time notifications | `[ROADMAP]` |

| Audit-log partition maintenance worker (startup ensure + daily roll, current month + 3) | `[RECENT]` |
| Gamma health check resolves its credential rather than counting a row | `[RECENT]` |
| Write-path probe on System Health | `[PLANNED]` — CR-012 |

### P. UI / Frontend

| Page | Status |
| --- | --- |
| Landing / Login | `[SHIPPED]` |
| Dashboard (stats, recent orders, quick actions) | `[SHIPPED]` |
| Work Orders list (filter, sort, archive toggle) | `[SHIPPED]` |
| Work Order detail (status, logs, approvals, GCC, actions) | `[SHIPPED]` |
| Submit Order form | `[SHIPPED]` |
| Sub-Agents configuration | `[SHIPPED]` |
| Workflow management | `[SHIPPED]` |
| Tools inventory | `[SHIPPED]` |
| Chat interface | `[SHIPPED]` |
| Workspace file browser (smart preview + download) | `[SHIPPED]` |
| Sandbox | `[IN DEV]` |
| Settings (LLM, operational) | `[SHIPPED]` |
| System Health | `[SHIPPED]` |
| User Management | `[SHIPPED]` |
| Architecture docs | `[SHIPPED]` |
| Attributions | `[SHIPPED]` |

---

## 3. Production Readiness Gaps

| ID | Severity | Description | Location | Status |
| --- | --- | --- | --- | --- |
| CR-001 | Critical | Tier-authority model not fully enforced at runtime (`MERGE` authority must be guaranteed Tier 1 only) | Orchestration + API policy layer | Open |
| CR-002 | Critical | Security hardening backlog is incomplete for production gate (auth bypass class, secret exposure class, dangerous debug execution class) | Auth, tools, sandbox, preview routes | Open |
| CR-003 | High | Backup admin pattern increases credential risk; replace with bootstrap flow + forced rotation | Auth provisioning | Open |
| CR-004 | High | Auth still coupled to Replit OIDC patterns | server/replit_integrations/ | Open |
| CR-005 | High | No mandatory security regression suite / release gates (0 critical, 0 high) | CI/CD + test strategy | Open |
| CR-006 | Medium | No versioned DB migrations (using db:push) | drizzle.config.ts | Open |
| CR-007 | Medium | Comprehensive unit/integration/E2E coverage missing for orchestration contracts | Backend + workflows | Open |
| CR-008 | Medium | Seed logic undocumented, no log when seed is skipped | seed.ts | Open |
| CR-009 | Low (UX) | Login button opens new tab in local dev | landing.tsx | Open |
| CR-010 | Low risk | qualityReview variable unguarded in orchestration | orchestration.ts:309 | Open |
| CR-011 | Low risk | JSON filter heuristic may over-filter valid JSON without HTML tags | pocketflow.ts:693-712 | Open |
| CR-012 | High | **Health checks that count rather than resolve.** System Health passed while every mutation 500'd (BUG-078) and again while every Gamma render 401'd (BUG-082) — every check on the page is a read. Gamma is fixed; the remaining three need the same treatment plus a write-path probe. | `routes/system_status.py` | Open |
| CR-013 | High | **`sandbox_docx` is a stub with no fallback route.** The only degraded surface on System Health that fails hard instead of degrading; `python-docx` is not installed. Blocks DOCX for SOP Master (1 of 2 surfaces) and Paul (1 of 8). Figma / 21st-Magic stubs are fine — both fall back to `sandbox_html` by design. | `adapter/sandbox_renderers.py:692` | Open |
| CR-014 | High | **Rules written into `AIDEN_SYSTEM_PROMPT` are dead code for any tenant with a custom prompt.** Klear's `aiden_tier_1.system_prompt` is 12,774 chars and replaces the runtime persona entirely; only `_AIDEN_OUTPUT_SCHEMA_TEMPLATE` reaches every tenant. Needs an invariant test asserting that tenant-invariant rules live in the appended block. | `runtime/tier_1_aiden.py` | Open |
| CR-015 | Medium | **Tier-1 tool assignment is not honoured.** `sub_agent_tools` lists 3 tools for `aiden_tier_1`; the runtime hands it all 17 from `TOOL_REGISTRY`. The Tools tab therefore misrepresents Tier-1 capability. Decide: honour the assignment, or mark Tier-1 as registry-wide in the UI. | `runtime/aiden_tools.py`, `views/sub_agents.py` | Open |
| CR-016 | Medium | **79 work orders frozen since 2026-05-19** (40 `pending`, 39 `processing`). No worker picks them up; nothing will clear them unaided. | `work_orders` data | Open |
| CR-017 | Medium | **50 of 54 workspace folders in the Klear tenant are test fixtures** (`A_*`, `B_*`, `sub_*`, `post_write_hook_repro_*`, `Drafts-renamed_*`) left by pytest runs against the live DB (BUG-081). New ones are now blocked; these need sweeping. | `workspace_folders` data | Open |
| CR-018 | Medium | **19 vitest integration failures** — permission-key vocabulary snapshot drift (96 keys in schema vs a 92-key snapshot) plus sandbox tenant resolution. Pre-existing; was concealed beneath the 60 partition failures until BUG-078 was fixed. | `tests/contract/`, `tests/integration/` | Open |
| CR-020 | Medium | **Operator-directed filing is not reachable.** `filing_folder_id_override` is honoured by `produce_output_package` but no caller passes it; documented as shipped in the first draft of BUG-084 and corrected. Needs Aiden to express a destination at dispatch time. | `runtime/tier_2_subagents.py:971` | Open |
| CR-021 | Medium | **`workspace_locate_output` returns nothing for pre-2026-09-05 artifacts when filtered by work order** — those rows carry no `workOrderId`. Falls back to recent outputs with an explicit note; a backfill would close it properly. | `runtime/tools/workspace.py` | Open |
| CR-019 | Low | **Tier-1 prompt crowding.** After this session's additions (search rubric, platform honesty, workspace routing) the live-LLM routing smoke `test_routing_compliance_to_nyx` flakes ~2 in 5, against 3-of-3 clean before. The prompt has grown materially in one day; the routing taxonomy may need re-tightening or the smoke re-baselining. | `runtime/tier_1_aiden.py`, `tests/test_tier_1_routing.py` | Open |

---

## 4. Performance Baseline

| Metric | Current | Target |
| --- | --- | --- |
| Tier 1 (Groq) | ~0.8s | Maintain |
| Tier 2 per LLM call (OpenRouter/Gemini) | 5-23s | <3s |
| Full pipeline (typical work order) | ~67s | <15s |
| Bottleneck | Sub-agent LLM latency (OpenRouter routing + Gemini response time) | Switch to faster providers or direct API |

---

## 5. Tech Debt, Security, and Infrastructure Backlog (Reprioritized)

| Priority | Item | Status | Impact |
| --- | --- | --- | --- |
| P0 | Runtime enforcement of GCC authority model (`CONTEXT/COMMIT/BRANCH/MERGE` permissions) | `[PLANNED]` | Prevents privilege drift and protects Tier boundaries |
| P0 | Security closure set: remove bypass patterns, remove static fallback credentials, lock debug/exec routes, harden preview paths, secret redaction policy | `[PLANNED]` | Mandatory for production trust and compliance |
| P0 | Release gates: security regressions + policy tests required before deploy | `[PLANNED]` | Stops high-risk regressions from shipping |
| P1 | Auth refactor to strategy pattern (decouple from Replit) | `[PLANNED]` | Enables reliable local/cloud installs |
| P1 | Database versioned migrations (drizzle-kit generate) | `[PLANNED]` | Safe schema evolution and rollback |
| P1 | Comprehensive test suite (unit + integration + E2E critical paths) | `[ROADMAP]` | Raises reliability to B+ threshold |
| P1 | Rate limiting on API routes | `[PLANNED]` | Abuse resistance and stability |
| P1 | File upload size limits and validation | `[PLANNED]` | Safety + predictable resource usage |
| P1 | **Memory Advisor abstraction boundary** — `MemoryAdvisor` interface + `NoOpMemoryAdvisor` default, two hook points in orchestration (pre-Tier 1 recall, post-completion store), `memoryAdvisor: "none" \| "muninn"` feature flag in settings schema. GCC remains authoritative. Enables clean MuninnDB drop-in for local installs in P2.3 with no further orchestration changes. | `[PLANNED]` | Preserves MuninnDB integration option for local SMB installs without blocking hardening |
| P2 | Export/import workspace bundles | `[ROADMAP]` | Better portability for local installs |
| P2 | Containerized deployment (Docker Compose) | `[ROADMAP]` | Easier reproducible deployment |
| P2 | OnlyOffice integration (alongside LibreOffice initially) | `[ROADMAP]` | Improves document conversion path over time |
| P2 | Mobile-responsive UI overhaul | `[ROADMAP]` | UX expansion without blocking core hardening |
| P2 | Error boundary and toast improvements on client | `[PLANNED]` | Better operator feedback loop |

---

## 6. B+ Reprioritized Delivery Plan (#CDX)

### Phase A — Secure Core and Authority (P0)

- Enforce Tier command authority in runtime and tests: Tier 1 merge-only, Tier 2 execution-only.
- Close critical security classes before new feature expansion.
- Keep UX unchanged while applying backend hardening controls.

### Phase B — Reliability and Deployment Confidence (P1)

- Complete auth strategy refactor and migration discipline.
- Add deterministic orchestration test coverage and release gating.
- Add rate limits and input validation on high-risk API surfaces.

### Phase C — Capability Expansion Without Heavy UX (P2)

- Deliver operator-visible features (2DO checklists, workspace context docs) only after P0/P1 gates pass.
- Expand integration surface (MCP external, sandbox, plugin marketplace) behind security and policy gates.
- Keep default UI fast and minimal; expose advanced controls progressively.

### Roadmap Impact Register (#CDX)

| Future Item | Dependency to De-Risk First | Impact if Dependency Slips |
| --- | --- | --- |
| External MCP server connections | P0 security closure + route hardening | Expanded attack surface and unstable ops |
| Sandbox expansion | P0 route controls + execution guardrails | Remote execution risk and incident exposure |
| SSO/OAuth2 support | P1 auth strategy refactor | Rework cost and delayed enterprise onboarding |
| Scheduled work orders | P1 idempotency + retry safety tests | Duplicate execution and stale automation |
| Plugin marketplace | P0/P1 security + governance controls | Untrusted extension risk |
| MuninnDB optional memory addon | P0 authority model enforced + **P1 Memory Advisor abstraction boundary (scoped in P1.4)** | Memory inconsistency and trust confusion — abstraction boundary now designed in P1, MuninnDB implementation drops in cleanly at P2.3 |

---

## 7. Summary Counts

| Category | Shipped | Recent | In Dev | Planned | Roadmap | Total |
| --- | --- | --- | --- | --- | --- | --- |
| Work Order Management | 8 | 0 | 0 | 2 | 1 | 11 |
| Tier 1 Policy Gate | 2 | 4 | 0 | 0 | 1 | 7 |
| Tier 2 PocketFlow | 7 | 2 | 1 | 0 | 0 | 10 |
| Sub-Agent System | 7 | 0 | 0 | 0 | 0 | 7 |
| GCC Memory | 7 | 0 | 0 | 0 | 0 | 7 |
| Workspace & Artifacts | 5 | 6 | 0 | 1 | 0 | 12 |
| Skills System | 4 | 1 | 0 | 0 | 1 | 6 |
| Workflows | 5 | 0 | 1 | 1 | 0 | 7 |
| Tools & Locker | 6 | 0 | 1 | 0 | 2 | 9 |
| Chat | 9 | 0 | 0 | 0 | 0 | 9 |
| Sandbox | 0 | 0 | 4 | 0 | 0 | 4 |
| Auth & RBAC | 4 | 2 | 1 | 0 | 1 | 8 |
| Approval System | 6 | 0 | 0 | 0 | 1 | 7 |
| Operational Settings | 5 | 0 | 0 | 0 | 0 | 5 |
| Monitoring | 5 | 0 | 0 | 0 | 2 | 7 |
| UI Pages | 14 | 0 | 1 | 0 | 0 | 15 |
| **Totals** | **89** | **14** | **9** | **4** | **10** | **126** |

---

## 8. Revision Log

| Date | Version | Changes |
| --- | --- | --- |
| 2026-03-05 | 1.0 | Initial features inventory. 123 features catalogued across 16 domains. Includes March 2026 session work (Tier 1 parsing, PPTX pipeline, file preview/download, workspace filing). Added Workspace Context Documents to planned features. |
| 2026-03-05 | 1.1 | Added Product Lineage section to Platform Overview. Clarified ALPHAv3 → IWO / TIB relationship: TIB becomes a specialized branch of a future IWO version. |
| 2026-03-05 | 1.2 | Added 2DO Checklist feature to Work Order Management [PLANNED]. Living checklist for at-a-glance work order status tracking across iterations. 124 total features. |
| 2026-03-05 | 1.3 | Added Workflow 2DO Checklist to Workflows [PLANNED]. Workflow-scope living checklist tracking multi-step progress. 125 total features. |
| 2026-03-05 | 1.4 | Added OnlyOffice integration to Tech Debt & Infrastructure Backlog [ROADMAP]. Planned to work alongside LibreOffice initially, then replace it (timeline TBD). Updated Tech Stack note. |
| 2026-03-06 | 1.5 | Reprioritized roadmap to B+ path with explicit P0/P1/P2 sequencing, expanded production-readiness gaps, and added roadmap impact register. Renamed roadmap file to versioned name `ROADMAP_FEATURES_v1.5.md`. #CDX #CDX-PRIORITY #CDX-SECURITY #CDX-GCC |
| 2026-03-06 | 1.6 | Added Memory Advisor abstraction boundary to P1 tech debt backlog. `MemoryAdvisor` interface + no-op default + two orchestration hook points + feature flag — 2-3 hours of P1 work that makes MuninnDB a clean drop-in at P2.3 without retrofitting hardened orchestration code. Updated Roadmap Impact Register for MuninnDB accordingly. Fixed MD040 (code block language) and MD034 (bare email address) lint warnings. |
| 2026-03-07 | 1.7 | App version v0.8.0. System prompt v0.4.0 uplift (proper progression order, Tier 1.5 PM, Memory Advisor spec, PPTX routing, rate limits, CHAT ACTION PROTOCOL). Added CHAT ACTION PROTOCOL features (CREATE_WORK_ORDER, EXECUTE_WORKFLOW, JSON sanitization). Skill auto-discovery shipped (skill-auto-import.ts, keyword match → Tool Locker import → step toolIds). BUG-014 through BUG-017 resolved. |
| 2026-03-07 | 1.8 | BUG-021 + BUG-022 resolved in Session 7. PDF pipeline now end-to-end: real binary generation + professional layout. Switched HTML→PDF renderer from LibreOffice headless to Playwright Chromium (`server/scripts/html-to-pdf.cjs`) — full CSS support, no blank-page/narrow-column issues. `injectPdfStyles` reworked: zero page margins, pandoc body override, fixed-position footer, pandoc title-block stripping. Updated Tech Stack to reflect Playwright Chromium. 126 total features. |
| 2026-03-13 | 1.9 | Desktop File Upload to Workspace shipped [RECENT]. `POST /api/workspace/upload` (JSON, base64 binary, 10MB max). UI: Upload File in New dropdown + drag-from-desktop drop zone overlay on file grid. Multi-file drop supported. 126 total features. |
| 2026-03-13 | 2.0 | **App v0.9.2.** PPTX workflow readiness: replaced generic PPTX skill with IWO2-native md-to-pptx pipeline spec, updated TOM/PM Alpha/Mark/Paul system prompts for workflow orchestration. 2DO Checklist feature shipped: `checklist_items` table, 4 API endpoints, 11 lifecycle hooks (orchestration + pocketflow), collapsible UI panel with phase badges and progress tracking. Contract drift fix (CODEX 5.4): reconciled workflow PM completion path with `tier2Result` model, fixed synthetic WorkOrder/Tier1Result shapes, added `toolsUsed` to Tier2Result schema, fixed 17 TS errors. All 50 tests pass. |
| 2026-03-14 | 2.1 | **App v0.9.5.** Gamma Template Registry shipped: `gamma_template_registry` + `gamma_generation_records` tables, three-layer model (Gamma template → content contract → LLM prompt), format-aware early resolution, `gammaPolicy` on SharedDict, content contract injection via `designContext`. HITL Candidate Review: `gammaDeliveryPolicy` on workflow templates (candidate_review mode), WO-level `gammaTemplateKey` override, three-level template precedence (WO > workflow > global), candidate persistence in `.local/gamma_candidates/`, 6 candidate API endpoints. 21st.dev Magic MCP integration for Mark/Tom. Dashboard/detail WO status sync fix. Auto-publish standalone workflow output to Sandbox. Version bump across all governance docs + app code. `.local/tmp/` added to .gitignore. |
| 2026-03-15 | 2.2 | Added roadmap note for an optional child-linked Work Order workflow architecture. Clarified this as an enterprise-grade alternative for workflows that need independent ownership, approvals, SLAs, queueing, and WO-level audit/checklist reuse, while keeping `workflow_step_runs` as the default model for simpler flows. |
| 2026-09-05 | 2.4 | **IWO3 Stand-Up, Grounding & Output Delivery.** Runtime restarted after a 3½-month idle; seven defects filed `BUG-078`..`BUG-084`. **Shipped:** audit-partition maintenance worker (every audited mutation had 500'd since 2026-07-01); open web search actually firing (0/6 → 6/6 probes) with source provenance in chat; catalogue-driven **Sub-Agent model dropdown** (live Groq/OpenRouter lists, 6h TTL cache with manual refresh, advisory chat-capability filter, current-model preservation); provider↔credential cross-wire guard on all four write paths plus an AST invariant gate; pytest live-database refusal guard; Gamma health check now resolves its credential; **Aiden workspace tools** (`workspace_create_folder` / `workspace_list_tree` / `workspace_locate_output`, registry 14 → 17); IWO2-shape output filing restored (`Outputs/<date>/<slug>_<id8>`) with operator override; workspace deep links (`?file=<id>`), rendered markdown, and `.md` / self-contained `.html` downloads. **New gaps opened:** CR-012..CR-019. 69+ new tests, every gate validated by reintroducing its defect. |
| 2026-03-15 | 2.3 | **Session 11 — Done Contract + Gamma PPTX Remediation + Pre-Replit Stabilization.** 15+ features shipped: Done Contract (4 artifact tracks + Wrap It Up HITL override), PPTX preflight validator, slide source shaper, post-Gamma compliance, PPTX review supplement, workflow PPTX post-processing safety net, local fallback reclassification, Gamma heartbeat, unified version identity, startup env validation, published-mode auth hardening, truthful /api/health, Gamma status in System Health UI, machine-local path portability, execution log + checklist + GCC metadata enrichment with model config. 4 bugs fixed (BUG-038 through BUG-041). UI fixes: WO header layout, chat three-dot menu, SplitPane gutter. Branding: FreedomForge.AI → Klear.ai / IOWA. |
