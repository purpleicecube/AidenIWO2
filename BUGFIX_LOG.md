# AIDEN IWO — Bug Fix Log & Code Review Findings

Repo: `purpleicecube/AidenIWO-or-TIB` (branch: `main`)
App version: rest-express 1.0.0

---

## Table of Contents

1. Bug Fixes (Session 1: 2026-03-03)
2. Bug Fixes (Session 2: 2026-03-04/05)
3. Code Review Findings
4. Performance Analysis
5. Infrastructure Changes
6. Session 11 — Gamma PPTX Remediation + Workflow Post-Processing (2026-03-15)

---

## Bug Fixes — Session 1 (2026-03-03)

Operator: Darrel Vaughn | Reviewer: Claude Code (Opus 4.6)

### BUG-001: No local PostgreSQL — app boots with broken database connection

| Field | Detail |
| --- | --- |
| Date | 2026-03-03 |
| Severity | Critical (blocker) |
| Status | Fixed, verified |
| Files | `.env`, Docker infrastructure |
| Symptom | Dev server started on port 5000 but threw `ETIMEDOUT` and `ECONNREFUSED` errors on every database call. `DATABASE_URL` in `.env` pointed to `localhost:5433` but no PostgreSQL instance was running locally. Seed failed, session store failed, all API routes returned errors. |
| Root Cause | The app was developed on Replit where PostgreSQL was provisioned automatically. The `.env` file's `DATABASE_URL=postgresql://aiden:aiden_local@localhost:5433/aiden_iwo` assumed a local Postgres on port 5433, but nothing was installed or running on the local machine. |
| Fix | Created a Docker container matching the `.env` credentials: `docker run -d --name aiden-postgres --restart unless-stopped -e POSTGRES_USER=aiden -e POSTGRES_PASSWORD=aiden_local -e POSTGRES_DB=aiden_iwo -p 5433:5432 -v aiden_pgdata:/var/lib/postgresql/data postgres:16-alpine`. Ran `npm run db:push` to create all Drizzle schema tables. |
| Verified | `docker exec aiden-postgres pg_isready` returns "accepting connections". Server starts clean with "Database seeded with sample work orders". |

---

### BUG-002: Session store fails — cannot log in locally

| Field | Detail |
| --- | --- |
| Date | 2026-03-03 |
| Severity | Critical (blocker) |
| Status | Fixed, verified |
| File | `server/replit_integrations/auth/replitAuth.ts` line 15 |
| Symptom | After PostgreSQL was running, hitting `/api/login` returned 500 or silently failed. Frontend landing page polling `/api/auth/user` every 2 seconds always returned 401. User could not authenticate. The login button opens `/api/login` in a new tab (`target="_blank"`), and the original tab polls for the session — but the session was never created. |
| Root Cause | `connect-pg-simple` session store was configured with `createTableIfMissing: false`. The `sessions` table did not exist in the fresh PostgreSQL database. Session creation failed silently inside `req.logIn()`, so the auto-login flow completed in the new tab but no session cookie was persisted. |
| Fix | Changed `createTableIfMissing: false` to `createTableIfMissing: true` on line 15 of `replitAuth.ts`. |
| Verified | `curl -c cookies -L localhost:5000/api/login` returns HTTP 200. `curl -b cookies localhost:5000/api/auth/user` returns: `{"id":"local-admin","email":"admin@localhost","firstName":"Local","lastName":"Admin","role":"admin"}`. |

---

### BUG-003: Work order crashes after quality review approves a revision

| Field | Detail |
| --- | --- |
| Date | 2026-03-03 |
| Severity | High |
| Status | Fixed, verified |
| File | `server/orchestration.ts` line 252 (declaration), line 491 (crash site) |
| Symptom | Work order processing completed the full pipeline — PocketFlow execution, quality review (score 0.88, recommendation: "approve") — then crashed with `TypeError: Assignment to constant variable.` Stack trace: `processWorkOrder (orchestration.ts:491)`. Status set to "failed" even though the deliverable was fully ready. |
| Root Cause | `tier2Result` was declared as `const` on line 252. The revision flow on line 491 attempted `tier2Result = currentTier2;` to update the variable with the revised Tier 2 output after quality approval. JavaScript's `const` prevents reassignment, causing a runtime crash. This bug only triggers when a work order goes through at least one revision cycle AND the revision passes quality review — first-pass approvals don't hit line 491. |
| Fix | Changed `const tier2Result: Tier2Result` to `let tier2Result: Tier2Result` on line 252. |
| Verified | Server restarted. Subsequent work orders that go through revision cycles complete without crashing. |

---

### BUG-004: Non-HTML deliverables assembled as raw JSON fragments

| Field | Detail |
| --- | --- |
| Date | 2026-03-03 |
| Severity | Medium |
| Status | Fixed, verified (via Session 2 end-to-end pipeline test) |
| File | `server/pocketflow.ts` lines 767-770 (`nodeBuildResponse()`) |
| Symptom | Work orders requesting documents (e.g., "create a project plan") returned concatenated JSON objects instead of a cohesive formatted deliverable. Aiden quality review flagged three issues: (1) "Multiple JSON objects concatenated instead of a single cohesive document", (2) "Final JSON object is truncated and incomplete", (3) "No clear narrative or formatted project-plan presentation". Quality score: 55%. Recommendation: request revision. |
| Root Cause | `nodeBuildResponse()` has two assembly paths: an HTML path (line 755) and a non-HTML `else` path (line 767). The HTML path correctly filters intermediate outputs using `isIntermediateOutput()` — which detects raw JSON planning metadata, step status messages, and structural outlines. The non-HTML path did **not** apply this filter. It blindly joined all `accumulatedOutputs` values with `\n\n`, including intermediate JSON fragments from planning and validation steps that were never meant to be part of the final deliverable. |
| Fix | Applied the same `isIntermediateOutput()` filter to the non-HTML path. Filters content outputs first; falls back to unfiltered concatenation only if filtering removes everything. |
| Before | `const allOutputs = Object.values(dict.accumulatedOutputs); combinedDeliverable = allOutputs.join("\n\n");` |
| After | `const contentOutputs = Object.entries(dict.accumulatedOutputs).filter(([_, v]) => !isIntermediateOutput(v)).map(([_, v]) => v); combinedDeliverable = contentOutputs.length > 0 ? contentOutputs.join("\n\n") : Object.values(dict.accumulatedOutputs).join("\n\n");` |
| Verified | Pending — retry of test work order "Alpha-Feature rollout project plan" after server restart. |

---

---

## Bug Fixes — Session 2 (2026-03-04/05)

Operator: Darrel Vaughn | Reviewer: Claude Code (Opus 4.6)

### BUG-005: Tier 1 LLM evaluation fails with Zod validation error

| Field | Detail |
| --- | --- |
| Date | 2026-03-04 |
| Severity | Critical (blocker) |
| Status | Fixed, verified |
| File | `server/llm-client.ts` (~line 585-614) |
| Symptom | Work orders blocked at Tier 1 with Zod validation errors. Fields `approved`, `reason`, and `handler` all undefined. Work orders stuck in "processing" state indefinitely. |
| Root Cause | LLM returned empty or malformed JSON. `safeJsonParse("{}")` returns `{}`, and `tier1ResponseSchema.parse({})` throws because all fields are required in the Zod schema. No fallback handling for empty responses. |
| Fix | Added three-part resilience: (1) empty response guard that returns a safe default when LLM returns empty/non-object, (2) flexible field mapping with aliases (`reason` OR `explanation` OR `message`, `handler` OR `sub_agent` OR `agent`), (3) debug logging for raw LLM responses. |
| Verified | Server restarted. Tier 1 now approves and routes work orders correctly. |

---

### BUG-006: Post-processing fails — `__dirname is not defined` in ESM mode

| Field | Detail |
| --- | --- |
| Date | 2026-03-04 |
| Severity | High |
| Status | Fixed, verified |
| File | `server/pocketflow.ts` (top of file + ~line 787) |
| Symptom | PocketFlow execution log showed "PPTX conversion failed: __dirname is not defined". PPTX post-processing never ran. Quality review saw only markdown text and flagged "Missing exported .pptx file". |
| Root Cause | Server runs in ESM mode via `npx tsx --env-file=.env server/index.ts`. ESM does not provide `__dirname` (a CommonJS global). The `nodePostProcess()` function used `path.resolve(__dirname, "../scripts/md-to-pptx.py")` which threw at runtime. |
| Fix | Added ESM-compatible polyfill: `import { fileURLToPath } from "url"; const __filename = fileURLToPath(import.meta.url); const __dirname = path.dirname(__filename);`. Changed script path to use `process.cwd()` for reliability: `path.resolve(process.cwd(), "server/scripts/md-to-pptx.py")`. |
| Verified | Post-processing log shows "PPTX generated: 9 slides, 41KB". |

---

### BUG-007: Quality review rejects deliverable despite .pptx being generated

| Field | Detail |
| --- | --- |
| Date | 2026-03-04 |
| Severity | Medium |
| Status | Fixed, verified |
| File | `server/llm-client.ts` (~line 1171), `server/orchestration.ts` (~line 320) |
| Symptom | Quality review scored 55-60% and flagged "Missing exported .pptx file" even though post-processing successfully generated a .pptx. |
| Root Cause | The POST-PROCESSING OUTPUT notice was appended at the END of the deliverable text, but the deliverable was truncated to 4000 chars for the quality review prompt. The notice was cut off. The quality review LLM only saw markdown text and concluded no .pptx existed. |
| Fix | Added `postProcessedFile` parameter to `runAidenQualityReview()`. Moved the post-processing notice to the TOP of the quality review prompt (before the deliverable text) with explicit instruction: "Do NOT flag 'missing .pptx' when a .pptx was generated via post-processing." Orchestration now passes `postProcessedFile` from tier2Result to quality review. |
| Verified | Quality review no longer flags missing file format when post-processing produced a binary file. |

---

### BUG-008: PPTX filed to wrong workspace folder (#Code_Blocks instead of #Documents)

| Field | Detail |
| --- | --- |
| Date | 2026-03-04 |
| Severity | Medium |
| Status | Fixed, verified |
| File | `server/workspace-filing.ts` (~line 622) |
| Symptom | Generated .pptx files were filed into `#Code_Blocks` folder instead of `#Documents`. |
| Root Cause | `resolveOutputFolder()` analyzed the markdown deliverable content and detected code-like patterns (markdown code blocks), routing the artifact to `#Code_Blocks`. It did not account for post-processed binary files that should always go to `#Documents`. |
| Fix | Added `hasPostProcessedFile` parameter to `resolveOutputFolder()`. When true, binary files bypass content analysis and always route to `#Documents`. |
| Verified | New work orders with .pptx post-processing file to `#Documents`. |

---

### BUG-009: Workspace preview shows raw base64 gibberish for binary files

| Field | Detail |
| --- | --- |
| Date | 2026-03-05 |
| Severity | Medium (UX) |
| Status | Fixed, verified |
| File | `client/src/pages/workspace.tsx` |
| Symptom | Clicking on a .pptx artifact in the workspace browser displayed thousands of characters of raw base64-encoded data in a `<pre>` tag. Unusable for operators. |
| Root Cause | The preview panel dumped `selectedArtifact.content` directly into a `<pre>` tag for ALL file types, regardless of whether the content was human-readable text or base64-encoded binary. |
| Fix | Added `getFileCategory()` classifier with 4 rendering modes: (1) `binary-download` — icon + file info + Download button for .pptx, .docx, .xlsx, .pdf, .zip, etc., (2) `image-preview` — inline `<img>` display, (3) `html-preview` — sandboxed `<iframe>`, (4) `text-preview` — `<pre>` with download link. Added `FILE_ICONS` map (20+ MIME types), `FILE_TYPE_LABELS` for human-readable names, and comprehensive download support. |
| Verified | Binary files show clean download button. Download endpoint returns valid files (confirmed with `file` command). |

---

### BUG-010: Download endpoint only handled .pptx — all other binary types returned corrupted data

| Field | Detail |
| --- | --- |
| Date | 2026-03-05 |
| Severity | Medium |
| Status | Fixed, verified |
| File | `server/routes.ts` (~line 2282) |
| Symptom | Only .pptx files could be downloaded correctly. Other binary types (.docx, .pdf, .xlsx, .zip) would return as raw text or with incorrect Content-Type headers. |
| Root Cause | The download endpoint only checked for `vnd.openxmlformats` MIME type when deciding to decode base64. Other binary MIME types were served as raw text. |
| Fix | Added comprehensive binary detection covering all Office formats, PDF, images, archives, and generic binary MIME types. Extension-based and MIME-based detection work together. |
| Verified | All binary types now decode correctly from base64 storage. |

---

## Bug Fixes — Session 3 (2026-03-05)

Operator: Darrel Vaughn | Reviewer: Claude Code (Sonnet 4.6)

### BUG-011: "sandbox" keyword in work order forces HTML assembly path, blocking PPTX quality review

| Field | Detail |
| --- | --- |
| Date | 2026-03-05 |
| Severity | High |
| Status | Fixed |
| File | `server/pocketflow.ts` lines 839-843 (`nodeBuildResponse()`) |
| Symptom | Work orders requesting a PowerPoint (.pptx) file that mentioned "sandbox" in their title or description (e.g., "save to sandbox", "sandbox presentation") were blocked at Tier 1 quality review with score 20%. Issues flagged: "Incorrect file format (HTML instead of .pptx)", "Missing saved .pptx file in sandbox/workspace", "Does not meet explicit deliverable type requirement". |
| Root Cause | `nodeBuildResponse()` evaluated `expectsHtml` using two conditions combined with `\|\|`: an explicit HTML keyword regex AND a bare `/sandbox/i.test(orderText)` check. The `/sandbox/i` catch-all was intended to detect HTML sandbox environments but matched any work order mentioning the word "sandbox" in any context. When true, `expectsHtml` routed assembly to `selectBestHtmlOutput()`, which discarded markdown content and returned an HTML mock-up. The downstream PPTX post-processing step (`nodePostProcess`) ran after `nodeBuildResponse`, received the HTML string instead of markdown, and either skipped conversion or produced a malformed file. Quality review then correctly rejected the HTML deliverable for a .pptx order. |
| Fix | Added a `requiresPptx` guard using the existing `detectRequiredFormat(dict)` function (already called later in the pipeline). When `requiresPptx` is true, `expectsHtml` is forced to `false` regardless of keyword matches. This ensures PPTX-bound orders always flow through the markdown assembly path and into the post-processing converter. |
| Before | `const expectsHtml = /\b(html\|...)\b/i.test(orderText) \|\| (/sandbox/i.test(orderText));` |
| After | `const requiresPptx = detectRequiredFormat(dict) === "pptx"; const expectsHtml = !requiresPptx && (/\b(html\|...)\b/i.test(orderText) \|\| (/sandbox/i.test(orderText)));` |
| Verified | Pending — requires re-run of PPTX work order containing "sandbox" in description. |

---

### BUG-012: Quality review ignores postProcessedFile override — flags PPTX format and filename issues despite .pptx being generated

| Field | Detail |
| --- | --- |
| Date | 2026-03-05 |
| Severity | High |
| Status | Fixed |
| File | `server/llm-client.ts` (~line 1223, `runAidenQualityReview()`) |
| Symptom | Quality review scored 55% and issued "request_revision" on a work order that successfully generated a .pptx (68KB, correct MIME type). Issues flagged: "Missing required .pptx file (WO-PPTX-AIDEN-001.pptx)", "Deliverable is in markdown/XML rather than a PowerPoint binary", "No embedded images or actual slide assets", "File naming and saving instructions not fulfilled". The postProcessedFile entry in the Tier 2 result confirmed the file existed and was correctly generated. |
| Root Cause | Two compounding issues: (1) The `postProcessedFile` override notice was placed **after** the Rules block in the quality review prompt. The Groq LLM (`openai/gpt-oss-120b`) treats the Rules section as authoritative and processes it first, then reads the override note as a secondary instruction that conflicts with rules already applied. The LLM ignored the note. (2) The work order description contained a specific filename "WO-PPTX-AIDEN-001.pptx" but the post-processing pipeline saves files as `<work_order_id>.pptx`. The LLM read the description requirement and flagged the specific filename as unmet, even though the file existed under a different name. |
| Fix | Moved the `postProcessedFile` override from after the capabilitiesNote into the Rules block itself, as an explicit numbered rule prefixed with `*** MANDATORY RULE ***`. The rule now explicitly: (1) declares file format = automatically satisfied, (2) forbids flagging markdown format, missing .pptx, binary format, or filename/save-location issues, (3) instructs the LLM to score the file format dimension as 1.0, and (4) redirects evaluation to content quality only (slide structure, completeness, writing quality). |
| Before | postProcessedFile note placed after `${capabilitiesNote}`, outside the Rules block |
| After | postProcessedFile override injected as last item inside the Rules block, before `${capabilitiesNote}` |
| Verified | Pending — requires re-run of fresh PPTX work order after server restart. |

---

### BUG-013: PPTX output collapses all slides into 3 slides — md-to-pptx.py cannot parse sub-agent structured format

| Field | Detail |
| --- | --- |
| Date | 2026-03-05 |
| Severity | High |
| Status | Fixed |
| Files | `server/scripts/html-to-pptx.js` (new), `server/pocketflow.ts` (`nodePostProcess`), DB `tools.skill_content` for `skill-pptx` |
| Symptom | A 5-slide PPTX work order produced a 3-slide deck: a title slide with only the work order title, a single content slide with all 5 slides' content + design notes + copy notes collapsed into one long bullet list, and a hardcoded "Thank You" closing slide. |
| Root Cause | `md-to-pptx.py` splits only on `##` headings as slide boundaries. The sub-agent (using the "Pptx" skill) outputs a structured format where each `## Slide N: Title` heading contains `### Design Notes` and `### Copy-Notes` sub-sections. The `###` sub-sections are not slide boundaries — they become additional bullets within the one `##` content block. Result: one giant content slide. The `md-to-pptx.py` script then adds a fixed title slide and "Thank You" = always 3 slides regardless of how many the work order requested. |
| Fix | Switched the PPTX post-processing pipeline to use `html2pptx.js` from `claude-office-skills` (Playwright + pptxgenjs). Three changes: (1) Created `server/scripts/html-to-pptx.js` — a new wrapper that extracts `<section class="slide">` elements from the sub-agent's HTML output, renders each as a standalone 720pt×405pt HTML file, and converts to PPTX slides via html2pptx.js. (2) Updated `nodePostProcess` in `pocketflow.ts` to detect HTML vs markdown deliverables and route to the correct converter (`html-to-pptx.js` for HTML, `md-to-pptx.py` as fallback for markdown). Timeout extended to 90s for html2pptx (Playwright browser launch per slide). (3) Replaced the `skill-pptx` DB skill prompt with a focused HTML-output spec: sub-agent now outputs a self-contained HTML document with `<section class="slide" style="width:720pt;height:405pt">` elements, one per slide, with inline CSS and web-safe fonts. |
| Verified | Pending — requires fresh PPTX work order submission after server restart. |

---

## Bug Fixes — Session 4 (2026-03-06/07)

Operator: Darrel Vaughn | Reviewer: Claude Code (Sonnet 4.6)

### BUG-014: DB system prompt contained artifact document — Aiden reading its own spec file as operational instructions

| Field | Detail |
| --- | --- |
| Date | 2026-03-06 |
| Severity | Critical (blocker) |
| Status | Fixed, verified |
| File | `shared/schema.ts` (default), DB `llm_settings` row |
| Symptom | Aiden's chat responses were generic, confused, and non-operational. Aiden could not route work orders, did not follow the 5-phase cycle, ignored GCC authority rules, and produced subpar outputs. Chat tests requesting multi-step workflows returned vague confirmations with no actual execution. |
| Root Cause | The `llm_settings.system_prompt` DB row contained the full `AIDEN_IWOv0.4.0.md` artifact document — the markdown spec file with the "Property/Value" metadata header and change-log table at the top. This is the governance/documentation file, not the operational prompt. The DB row was seeded from an earlier state where the wrong content was set. Subsequent changes to `schema.ts` default do not backfill existing DB rows (Drizzle schema defaults only apply on INSERT, not UPDATE). |
| Fix | (1) Updated `shared/schema.ts` `systemPrompt` column default to the full v0.4.0 operational prompt (the raw `text` block inside the artifact doc's code fence). (2) Ran a direct Node.js pg-client script to UPDATE the existing `llm_settings` WHERE id = `'default'` with the correct 12,345-character operational prompt extracted from `schema.ts`. |
| Verified | `SELECT length(system_prompt) FROM llm_settings` returned 12,345. Chat responses immediately shifted to structured JSON decisions, 5-phase orchestration language, and correct GCC authority framing. |

---

### BUG-015: Aiden cannot create or activate work orders and workflows from chat — no action emission protocol

| Field | Detail |
| --- | --- |
| Date | 2026-03-06 |
| Severity | High |
| Status | Fixed, verified |
| Files | `shared/schema.ts` (system prompt), `server/routes.ts` (chat message handler) |
| Symptom | Asking Aiden to "build a website for Iowa tourism" in chat produced a structured JSON plan but no actual workflow or work order was created. The Workflows page remained empty. Sub-agents were never dispatched. Aiden described actions but did not execute them. |
| Root Cause | The system prompt had no mechanism for Aiden to signal executable actions back to the platform. The chat handler parsed LLM replies only for `<!-- AIDEN_ACTION:CREATE_WORK_ORDER:{...} -->` blocks — but the prompt never instructed Aiden to emit these blocks. Without the CHAT ACTION PROTOCOL in the prompt, Aiden always responded in natural language only, never emitting machine-parseable action blocks. |
| Fix | Added **CHAT ACTION PROTOCOL** section to the system prompt (before STANCE). The section defines two action block formats: `<!-- AIDEN_ACTION:CREATE_WORK_ORDER:{...} -->` (JSON with title, description, type, priority, autoProcess) and `<!-- AIDEN_ACTION:EXECUTE_WORKFLOW:{...} -->` (JSON with name, goal, category, steps array including stepKey, name, description, assignTo, order). Protocol rules: emit once per response, strip from visible reply, prefer EXECUTE_WORKFLOW for multi-step tasks. |
| Verified | After prompt update and DB refresh, chat test requesting multi-step workflow produced `EXECUTE_WORKFLOW` action block. Workflow template, steps, and execution record appeared in DB. Workflow appeared in Workflows UI. |

---

### BUG-016: Chat-triggered workflows had no skills assigned — sub-agents executed steps without tool context

| Field | Detail |
| --- | --- |
| Date | 2026-03-06 |
| Severity | Medium |
| Status | Fixed — deployed, pending live test |
| Files | `server/skill-auto-import.ts` (new), `server/routes.ts`, `server/orchestration.ts` |
| Symptom | Workflows created from chat (via EXECUTE_WORKFLOW action blocks) had `toolIds: []` on every step. Sub-agents executed steps with no skill context — no brand guidelines, no frontend-design skill, no web-artifacts-builder — producing generic, low-quality outputs. The Tool Locker showed only the manually imported PPTX skill. |
| Root Cause | The EXECUTE_WORKFLOW handler in `routes.ts` set `toolIds` from `step.tools` in the action JSON (always `[]` since Aiden's action block doesn't enumerate tool IDs). No mechanism existed to automatically match step descriptions to available skills and import them. |
| Fix | Created `server/skill-auto-import.ts` — a shared utility with `autoImportSkillsForDescription(description, name)` that: (1) keyword-matches against all 16 skills in `.local/skills/` using a curated keyword map covering brand-guidelines, canvas-design, doc-coauthoring, docx, frontend-design, internal-comms, mcp-builder, pdf, pptx, skill-creator, slack-gif-creator, theme-factory, webapp-testing, web-artifacts-builder, xlsx, (2) returns tool IDs for already-imported skills (no re-import), (3) imports new matching skills into the Tool Locker using identical logic to the manual import-skill route, (4) returns merged tool IDs. Wired into two locations: (a) `routes.ts` EXECUTE_WORKFLOW handler — auto-imports before each `storage.createWorkflowStep()` call and merges IDs into `toolIds` field, (b) `orchestration.ts` `getToolsForStep()` — auto-imports at step execution time as a safety net for existing or non-chat-created steps. Keyword map example: `frontend-design` triggers on html, css, frontend, web, website, ui, interface, page; `pptx` triggers on pptx, powerpoint, presentation, slide, deck. |
| Verified | Fix deployed — app restarted on port 5001 with `skill-auto-import.ts` active. Awaiting live workflow test to confirm skills appear in Tool Locker and are assigned to steps. |

---

## Bug Fixes — Session 5 (2026-03-07)

Operator: Darrel Vaughn | Reviewer: Claude Code (Sonnet 4.6)

### BUG-017: LLM emits `}}` double-brace at end of EXECUTE_WORKFLOW JSON — silent parse failure, workflow never created

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | High |
| Status | Fixed — deployed, pending live retest |
| File | `server/routes.ts` (EXECUTE_WORKFLOW handler, ~line 3082) |
| Symptom | Chat request "create a test workflow to build a PPT introducing Aiden IWO to the world — 5 slides only, Apple Inc style" caused Aiden to emit a correctly-structured EXECUTE_WORKFLOW action block. No workflow template, steps, or execution record appeared in the DB. Aiden subsequently told the user "I actually did create a workflow" — this was false. The Workflows dashboard remained empty. Confirmed via DB query: `SELECT id, name FROM workflow_templates` returned only the earlier Iowa test — no PPT workflow row. |
| Root Cause | The LLM generated `]}}` (double closing brace) instead of `]}` at the end of the steps array JSON. The EXECUTE_WORKFLOW regex `(\{.*\})` uses a greedy `.*` which captured the full string including the extra `}`. `JSON.parse` received malformed JSON and threw `SyntaxError: Unexpected token }`. This error was silently caught by the `catch (wfErr)` block. Critically, `reply = contentLines.join("\n")` — which strips the action block from the visible reply — was located INSIDE the try block, after the JSON.parse call. So when JSON.parse threw, the reply was never updated, the action block remained in the reply string, and the reply was saved verbatim to `chat_messages`. Net result: no workflow created, no user-visible error, Aiden's next response was confused and claimed success. |
| Root cause confirmed by | `docker exec aiden-postgres psql -U aiden aiden_iwo -c "SELECT content FROM chat_messages WHERE id='8dd1cd72...'"` — the stored assistant message contained the raw action block with `}}` at end, proving it was never processed. |
| Fix | Three targeted changes to `server/routes.ts`: (1) Added `isValidJson(s: string): boolean` helper at module level (try/catch JSON.parse, return bool). (2) In the EXECUTE_WORKFLOW handler, before `JSON.parse(actionJson)`, apply sanitization: trim the captured JSON string, then loop stripping one trailing `}` at a time until `isValidJson()` returns true — handles 1 or more extra braces. (3) Moved `reply = contentLines.join("\n")` to immediately after the `if (workflowActionLines.length > 0 && canCreateOrders)` check — outside all try/catch blocks — ensuring action blocks are always stripped from the visible reply regardless of whether workflow creation succeeds or fails. Added `if (!execution) continue` null-guard after `startWorkflowExecution` call. |
| Before | `reply = contentLines.join("\n")` on line ~3162, inside try block, after `JSON.parse`. Executed only on success. |
| After | `reply = contentLines.join("\n")` on line ~3084, immediately after entering the `if` block. Executed unconditionally. |
| Verified | App restarted on port 5001 (uptime confirmed, v0.8.0 health check passing). Awaiting fresh PPT workflow test — expected result: template + 5 steps + execution appear in DB and Workflows UI, action block stripped from Aiden's visible reply. |

---

### BUG-018: Chat LLM hangs indefinitely on Groq rate limit — UI stuck in "thinking" state

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | High |
| Status | Fixed — deployed |
| File | `server/llm-client.ts` (`chatWithAiden`, ~line 419) |
| Symptom | After heavy workflow/work order processing consumed the Groq TPM quota (243,318 of 250,000 tokens used), a simple "hello" chat message caused the UI to show "Aiden is thinking..." indefinitely. The spinner never resolved. No error was surfaced to the user. Only a server restart would clear it. |
| Root Cause | `chatWithAiden` instantiates the OpenAI SDK client with no `timeout` or `maxRetries` override: `new OpenAI({ apiKey, baseURL })`. The OpenAI SDK default is `maxRetries: 2` with exponential backoff. On a 429 rate limit error, the SDK silently retries twice with increasing delays (potentially 30-60+ seconds), then throws. The `catch` block returns a user-facing error string, but the total wait time exceeds any reasonable UX threshold, leaving the UI spinner running. |
| Fix | Added `timeout: 45000` (45s max) and `maxRetries: 1` to the OpenAI client instantiation in `chatWithAiden`: `new OpenAI({ apiKey, baseURL, timeout: 45000, maxRetries: 1 })`. At most one retry; total elapsed capped at 45 seconds before the catch block returns a clear error message. |
| Verified | Server restarted. If rate limit is hit again, chat will respond with an error message within 45s rather than hanging indefinitely. |

---

### BUG-019: EXECUTE_WORKFLOW handler crashes on `createExecutionLog` — NOT NULL constraint on `work_order_id`

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | Medium |
| Status | Fixed — deployed |
| File | `server/routes.ts` (EXECUTE_WORKFLOW handler, `createExecutionLog` call) |
| Symptom | Every chat-triggered workflow creation threw: `error: null value in column "work_order_id" of relation "execution_logs" violates not-null constraint`. The error was caught by the outer try/catch so the workflow was still created, but the console showed the stack trace on every workflow event. In edge cases, earlier successful `actionResults.push` may not have committed. |
| Root Cause | The EXECUTE_WORKFLOW handler called `storage.createExecutionLog({ workOrderId: null as any, ... })` to audit the workflow creation event. The `execution_logs.work_order_id` DB column has a NOT NULL constraint — it was designed for work order events only. Chat-originated workflow events do not have an associated work order ID. Passing `null as any` bypasses TypeScript but hits the DB constraint at runtime. |
| Fix | Removed the `createExecutionLog` call from the EXECUTE_WORKFLOW handler entirely and replaced it with a `console.log`. Workflow execution tracking is already handled by the `workflow_executions` and `workflow_step_runs` tables. The execution log is not required here. |
| Verified | Server restarted. No more NOT NULL constraint errors in logs when workflows are created from chat. |

---

### BUG-020: html-to-pptx.js crashes with `require is not defined` — CommonJS script in ESM package

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | High |
| Status | Fixed — deployed |
| Files | `server/scripts/html-to-pptx.cjs` (new), `server/pocketflow.ts` |
| Symptom | Every PPTX work order that produced HTML slides (the new html2pptx pipeline) failed at the post-processing step with: `ReferenceError: require is not defined in ES module scope`. The .pptx file was never generated. Quality review then flagged "missing .pptx file" and rejected the deliverable. |
| Root Cause | `server/scripts/html-to-pptx.js` uses CommonJS `require()` syntax (`const fs = require('fs')`, `const html2pptx = require(...)`). The project's `package.json` has `"type": "module"`, which makes Node.js treat all `.js` files in the project as ES modules. In ESM mode, `require` is not available — the script crashed immediately on line 17. |
| Fix | Copied `html-to-pptx.js` to `html-to-pptx.cjs`. The `.cjs` extension explicitly marks the file as CommonJS regardless of `package.json` `"type"` setting. Updated `server/pocketflow.ts` `nodePostProcess` to reference `html-to-pptx.cjs` instead of `.js`. |
| Verified | Server restarted. Next HTML-slide PPTX work order will use the `.cjs` script, which can correctly load `require('fs')` and the html2pptx library. |

---

## Code Review Findings

Issues discovered during investigation that are not bugs but represent risks, tech debt, or improvement opportunities.

### CR-001: Auth system tightly coupled to Replit OIDC

| Field | Detail |
| --- | --- |
| Severity | Design debt |
| File | `server/replit_integrations/auth/replitAuth.ts` |
| Finding | The entire auth system was built around Replit's OpenID Connect flow (`openid-client` library, `REPL_ID` env var, Replit-specific OIDC discovery URL). Running locally required a complete rewrite of the auth module. The file is still located at `server/replit_integrations/auth/` even though it no longer uses Replit auth. |
| Recommendation | Consider abstracting auth behind a strategy interface so switching between Replit OIDC (production) and local auto-login (dev) is a config toggle, not a code rewrite. Consider renaming the directory to reflect its actual purpose. |

### CR-002: No database migrations directory

| Field | Detail |
| --- | --- |
| Severity | Low risk |
| File | `drizzle.config.ts` |
| Finding | `drizzle.config.ts` references a `./migrations` directory, but no `migrations/` directory exists in the repo. Schema changes are applied exclusively via `npm run db:push` (Drizzle Kit push), which directly mutates the database schema without versioned migration files. |
| Recommendation | For production use, generate and commit migration files (`drizzle-kit generate`) so schema changes are auditable and reversible. `db:push` is fine for dev but risky for production databases with real data. |

### CR-003: Seed logic is safe but undocumented

| Field | Detail |
| --- | --- |
| Severity | Informational |
| File | `server/seed.ts` lines 6-8 |
| Finding | `seedDatabase()` checks if `work_orders` has any rows and returns immediately if data exists. It only seeds 5 sample work orders into an empty database. It does NOT touch `llm_settings`, `sub_agents`, `operational_settings`, or any configuration tables. This is safe behavior but is not documented anywhere — operators may worry about data loss on restart. |
| Recommendation | Add a comment or log message: "Seed skipped — database already has data." |

### CR-004: Login button opens in new tab — potential UX confusion

| Field | Detail |
| --- | --- |
| Severity | Low (UX) |
| File | `client/src/pages/landing.tsx` |
| Finding | The "Sign In" button uses `target="_blank"` and `rel="noopener noreferrer"`. In the Replit OIDC flow, this made sense (redirect to external auth provider). With local auto-login, it opens a new tab that immediately redirects to `/` while the original tab polls `/api/auth/user` every 2 seconds. This works but creates a briefly confusing two-tab experience for local dev. |
| Recommendation | For local dev, consider removing `target="_blank"` or detecting local mode and using same-tab navigation. |

### CR-005: `qualityReview` declared with `let` but no initial value guard

| Field | Detail |
| --- | --- |
| Severity | Low risk |
| File | `server/orchestration.ts` line 309 |
| Finding | `qualityReview` is declared as `let qualityReview;` (no type annotation, no initial value). It gets assigned later in the flow, but if the quality review LLM call fails in an unexpected way, downstream code (lines 498-514) references `qualityReview.score` and `qualityReview.issues` without null checks, which could throw a different runtime error. |
| Recommendation | Initialize with a safe default: `let qualityReview: { score: number; issues: string[]; recommendation: string; summary?: string } = { score: 0, issues: [], recommendation: "pending" };` |

### CR-006: `isIntermediateOutput()` heuristic may over-filter valid JSON deliverables

| Field | Detail |
| --- | --- |
| Severity | Low risk |
| File | `server/pocketflow.ts` lines 693-712 |
| Finding | `isIntermediateOutput()` flags any output that starts with `{` or `[` and parses as valid JSON as "intermediate" — unless it contains HTML tags. This means if a work order legitimately requests JSON output (e.g., "generate an API schema", "create a config file"), the deliverable could be incorrectly filtered out. The fallback (line 769) catches this by using unfiltered output when filtering leaves nothing, but it's a fragile safety net. |
| Recommendation | Consider checking the work order type/description for JSON-output intent before applying the filter, similar to how HTML detection works via regex on the order text. |

---

## Performance Analysis

### PERF-001: Sub-agent LLM latency is the primary bottleneck

| Field | Detail |
| --- | --- |
| Date | 2026-03-03 |
| File | `server/pocketflow.ts`, `server/llm-client.ts` |

**Observed timeline** for test work order "Alpha-Feature rollout project plan":

| Step | Timestamp | Duration | Provider |
| --- | --- | --- | --- |
| Submitted | 20:41:54.210 | — | — |
| Tier 1 Policy Gate | 20:41:54.231 | — | Groq |
| Tier 1 Policy Decision | 20:41:55.015 | **0.8s** | Groq (`openai/gpt-oss-120b`) |
| PocketFlow: PlanSteps | 20:41:55.038 → 20:42:14.589 | **19.5s** | OpenRouter (`google/gemini-2.5-pro-preview`) |
| PocketFlow: ExecStep 1 | 20:42:14.596 → 20:42:37.646 | **23.0s** | OpenRouter |
| PocketFlow: ExecStep 2-5 | 20:42:37.646 → 20:42:37.688 | ~0s (batched) | — |
| PocketFlow: ExecStep 6 | 20:42:37.688 → 20:42:54.104 | **16.4s** | OpenRouter |
| PocketFlow: ExecStep 7 | 20:42:54.104 → 20:42:59.664 | **5.6s** | OpenRouter |
| PocketFlow: ExecStep 8 | 20:42:59.664 → 20:43:01.714 | **2.0s** | OpenRouter |
| **Total pipeline** | | **~67s** | |

**Finding:** Tier 1 (Groq) is fast (~0.8s). Tier 2 sub-agent uses OpenRouter → Gemini 2.5 Pro Preview, which adds 5-23 seconds per LLM call. PocketFlow makes 8+ sequential calls (1 plan + N exec + evaluate + possibly refine), so total latency compounds to 60-90+ seconds for a simple work order.

**HTTP route latency** is not the issue — all Express endpoints respond in 10-61ms.

**Options identified:**

| Option | Expected Impact | Trade-off |
| --- | --- | --- |
| Switch sub-agent to Groq / `llama-3.3-70b-versatile` | ~5-10x faster (est. 10-15s total) | Slightly lower quality than Gemini 2.5 Pro |
| Switch sub-agent to Groq / `llama-3.1-8b-instant` | ~10-20x faster (est. 5-8s total) | Lower quality, suitable for simple tasks only |
| Switch to OpenRouter / `google/gemini-2.0-flash` | ~3-5x faster | Good quality, much cheaper |
| Switch to OpenRouter / `anthropic/claude-3.5-haiku` | ~3-5x faster | Very good quality |
| Add direct `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Eliminates OpenRouter routing latency | Requires additional API key |
| Multiple sub-agents with different models | Route simple tasks to fast model, complex to quality model | Configuration complexity |

**Note:** PocketFlow already supports parallel step execution (steps with `dependencies: []` run concurrently). The LLM planner can declare independent steps, but the per-call latency of Gemini 2.5 Pro Preview dominates regardless.

---

## Infrastructure Changes (2026-03-03)

Changes made to enable local development. These are not bugs but new infrastructure.

| Change | Detail | Files |
| --- | --- | --- |
| Local PostgreSQL | Docker container `aiden-postgres` (postgres:16-alpine) on port 5433. Named volume `aiden_pgdata` for persistence. Restart policy: `unless-stopped` (survives reboots). Credentials match `.env`: user=`aiden`, pass=`aiden_local`, db=`aiden_iwo`. | Docker |
| Auth rewrite (pre-existing) | `replitAuth.ts` had already been rewritten to replace Replit OIDC with local auto-login as "local-admin" (no password). Cookie `secure: false` for HTTP local dev. Session user shape matches `req.user.claims.sub` pattern expected by `routes.ts`. | `server/replit_integrations/auth/replitAuth.ts` |
| Dev script env loading | `npm run dev` updated to use `tsx --env-file=.env` so `.env` variables load automatically without `dotenv`. | `package.json` |
| Automated backups | `script/backup-db.sh` — compressed daily `pg_dump` with 7-day rotation. Cron job installed at 2:00 AM. First backup: `aiden_iwo_20260303_124256.sql.gz` (16K). Restore: `gunzip -c <file>.sql.gz \| docker exec -i aiden-postgres psql -U aiden aiden_iwo`. | `script/backup-db.sh`, crontab |
| Dev convenience script | `script/local-dev.sh` — subcommands: `start` (DB + schema + app), `stop`, `status`, `reset` (destructive — deletes volume). | `script/local-dev.sh` |
| Gitignore updates | Added `backups/` to `.gitignore` to prevent database dumps from being committed. | `.gitignore` |

---

---

## Feature Implementations — Session 6 (2026-03-07)

Operator: Darrel Vaughn | Reviewer: Claude Code (Sonnet 4.6)

Session 6 implemented two platform capability gaps identified during the Mark sub-agent CODEX integration. These are feature additions, not bug fixes.

### FEAT-001: Execution mode plumbing — `getToolsForStep` now respects `operational_settings.current_mode`

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Status | Implemented, deployed, verified |
| Files | `server/orchestration.ts` (`getToolsForStep`, ~line 1260) |
| Gap | Skill auto-import ran unconditionally regardless of platform execution mode. In `manual` mode, sub-agents are expected to request tools explicitly via the Tool Needed protocol — not have skills injected automatically. |
| Implementation | Added `storage.getOperationalSettings()` call at the top of `getToolsForStep`. Reads `currentMode` from the `operational_settings` table (default: `semi_autonomous`). Auto-import runs only when mode is `semi_autonomous` or `autonomous`. In `manual` mode, skill auto-import is skipped and a console log is emitted: "Manual mode — skipping skill auto-import for step X. Sub-agent must request tools explicitly." Explicit `toolIds` assigned to the step are always applied regardless of mode. |
| Behavior matrix | `manual`: No auto-import. Sub-agent uses explicitly assigned tools only, or emits Tool Needed signal. `semi_autonomous`: Auto-imports skills matching step description from skill catalog. `autonomous`: Same as semi_autonomous (full auto-provision within policy guardrails). |
| Verified | Server restarted on port 5001, logs show expected behavior on startup. DB confirms `operational_settings.current_mode = semi_autonomous`. |

---

### FEAT-002: "Tool Needed" signal parser — auto-provisioning from step output

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Status | Implemented, deployed, verified |
| Files | `server/orchestration.ts` (`handleToolNeededSignal` function + `advanceWorkflowExecution` wiring, ~lines 1167–1252 and ~993–999) |
| Gap | Mark and other CODEX-governed sub-agents emit a structured "Tool Needed" block when they lack a required capability. The platform had no mechanism to detect this signal, provision the tool, and retry the step. The block was emitted into step output and ignored. |
| Implementation | New `handleToolNeededSignal(output, stepDef, mode, execution, stepRun, executionId)` function inserted before `getToolsForStep`. Detection: regex matches `**Tool Needed**: [Tool Name]` or `Tool Needed: [Tool Name]` in step output string. Mode-aware response: (1) `manual` → marks step as `awaiting_operator`, execution/work order as `awaiting_operator`, creates HITL execution log, returns `hitlBlocked: true`. (2) `semi_autonomous` / `autonomous` → calls `autoImportSkillsForDescription(toolName)` to find matching skill, merges imported IDs into `stepDef.toolIds` via `storage.updateWorkflowStep`, creates "Auto-Provisioned Tool" execution log, resets step run to `pending` (nulls output/timestamps), returns `retryQueued: true`. Wired into `advanceWorkflowExecution` BEFORE the step is marked as completed: reads platform mode, calls `handleToolNeededSignal`, branches on result. If `hitlBlocked` → return current execution state. If `retryQueued` → tail-call `advanceWorkflowExecution` to immediately re-run step with new tools. |
| Supported signal format | Markdown bold: `**Tool Needed**: [PPTX Skill]` or plain: `Tool Needed: PPTX Skill`. Square brackets stripped from tool name before lookup. |
| Verified | Server running. DB Mark prompt updated with full CODEX Tool Needed protocol block. Awaiting live test with Mark executing a PPTX workflow step. |

---

### FEAT-003: Mark sub-agent prompt — B04_MKTG addendum integrated

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Status | Implemented, deployed, verified |
| Files | DB `sub_agents.llm_system_prompt` (Mark ID: `e0aa815d-cc1f-4274-94bc-66b49d38a0bc`), `server/scripts/update-mark-prompt.cjs` |
| Gap | Mark's system prompt contained only CODEX governance blocks (AUTHORIZATION RULES, WORKFLOW EXECUTION RULES, TOOL ORCHESTRATION AUTHORITY). The B04_MKTG persona addendum (stored at `+6PLOCKER/Locker_FFAI/TIB_FFAI/B04_MKTG/B04_MKTG/03_PROMPT_ADDENDUM_MARK.txt`) had never been incorporated — Mark lacked the marketing-domain expertise content. |
| Implementation | Wrote `server/scripts/update-mark-prompt.cjs` (pg direct connection). Built complete 5,632-character prompt incorporating: IDENTITY (Empathetic Architect archetype), CORE OPERATING STYLE (hypothesis-first, board-ready), SIGNATURE STRENGTHS (5 domains: data synthesis, strategic narrative, omnichannel mastery, agility, regulatory savvy), LEADERSHIP BEHAVIOR, DEFAULT DECISION HEURISTICS, PREFERRED DELIVERABLES (6 types), MISSING INFO HANDLING, HARD BOUNDARIES (4 never-do rules), TONE & VOICE — followed by full AUTHORIZATION RULES, WORKFLOW EXECUTION RULES, and TOOL ORCHESTRATION AUTHORITY blocks with mode-aware provisioning behavior table. |
| Verified | `UPDATE sub_agents SET llm_system_prompt = ... WHERE id = 'e0aa815d...'` confirmed "Mark prompt updated successfully (5632 chars)". DB re-queried: `prompt_start` begins with "# IDENTITY\nYou are Mark, the Marketing Director sub-agent on the AIDEN IWO platf". |

---

## Bug Fixes — Session 7 (2026-03-07)

Operator: Darrel Vaughn | Reviewer: Claude Code (Sonnet 4.6)

### BUG-021: PDF artifact never generated — `skill-pdf` is prompt-injection only, no binary output

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | High (user-visible: promised artifact never delivered) |
| Status | Fixed, verified |
| Files | `server/pocketflow.ts` (`detectRequiredFormat`, `nodePostProcess`), `server/workspace-filing.ts` (post-processed artifact filing) |
| Symptom | Work orders with "PDF" in the title completed without an artifact. The LLM (Mark) claimed to generate a PDF but only produced markdown text. The `tier2Result.postProcessedFile` field was always `undefined`. No PDF appeared in the Artifacts folder. |
| Root Cause | `skill-pdf` and `skill-canvas-design` are `prompt_injection` execution mode tools — they inject guidance text into the LLM's system prompt. They do not generate binary files. The LLM fabricates file creation claims based on the injected guidance. `nodePostProcess` in `pocketflow.ts` only handled `pptx` format; there was no PDF conversion path. `detectRequiredFormat` only returned `"pptx"` or `null`, never `"pdf"`. Even if PDF was detected, there was no conversion logic. |
| Fix | Four files changed. `detectRequiredFormat` — added "pdf" return type; explicit keyword match on "pdf" or "portable document" now takes priority over skill-based detection, preventing PPTX skills from overriding explicit PDF requests. `nodePostProcess` — added PDF branch: writes deliverable markdown to temp file, runs pandoc to HTML, then libreoffice headless to PDF binary; copies result to `.local/workspace/05_Artifacts/`; sets `dict.postProcessedFile` with path, mimeType, and size. `nodeBuildResponse` — added `requiresPdf` guard alongside `requiresPptx` to prevent PDF-bound orders routing to HTML assembly. `workspace-filing.ts` — generalized post-processed artifact registration: derives extension from mimeType (pdf vs pptx vs bin), uses correct format tag, removes hardcoded "pptx" strings. |
| Tool chain | pandoc 3.6.2 (markdown → HTML), LibreOffice 7.4.7 headless (HTML → PDF). No wkhtmltopdf or weasyprint required. |
| Verified | End-to-end test: work order "Executive Summary PDF" → real 65KB 7-page PDF at `.local/workspace/05_Artifacts/Executive_Summary_PDF.pdf`. After operator accept: artifact `executive-summary-pdf.pdf` created in DB with `mimeType: application/pdf`, tags `['auto-filed', 'deliverable', 'pdf', 'standard', 'post-processed']`. Visible in Artifacts page. |

---

### BUG-022: PDF rendered by LibreOffice has blank first page, non-full-width header/footer, and narrow centered content

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | Medium (visual quality — PDF was generated, but layout was broken) |
| Status | Fixed, verified |
| Files | `server/pocketflow.ts` (`injectPdfStyles`), `server/scripts/html-to-pdf.cjs` (new) |
| Symptom | Generated PDFs had: (1) a blank first page caused by CSS overflow from negative margin bleed attempt; (2) header and footer appearing as small dark boxes in the top-left corner, not full-width bars; (3) all content rendering as a narrow centered column (~60% of page width) instead of filling the page. |
| Root Cause | Three interacting issues. First: LibreOffice HTML→PDF does not support `@page { margin: 0 }`, `position: fixed`, or negative margins — all commonly used for full-bleed header/footer. Second: pandoc's default HTML template injects `body { max-width: 36em; margin: 0 auto; }` which constrains content to a narrow centered column; LibreOffice does not apply `!important` override CSS correctly. Third: the header used `margin: -22mm -20mm 0 -20mm` to bleed to page edge, which LibreOffice interprets by pushing content down, creating a blank overflow page. |
| Fix | Replaced LibreOffice headless with **Playwright Chromium** for HTML→PDF conversion. Chromium fully supports `@page { margin: 0 }`, `position: fixed`, and CSS overrides. New script: `server/scripts/html-to-pdf.cjs` — accepts `--input`/`--output`, launches headless Chromium (from `claude-office-skills` shared browser cache), sets A4 viewport (794px), exports with `printBackground: true` and zero margins. Updated `injectPdfStyles`: removed all negative margins; added `html, body { max-width: none !important; width: 100% !important; margin: 0 !important; }` to defeat pandoc's narrow body; `position: fixed; bottom: 0; left: 0; right: 0` for footer (works in Chromium print). Also fixed pandoc title block stripping: was targeting bare `<h1>` at body start; now strips `<header id="title-block-header">` wrapper that pandoc actually emits. |
| Verified | Local test: `test-pdf-layout.md` → pandoc HTML → `injectPdfStyles` CSS injection → `html-to-pdf.cjs` (Playwright Chromium) → 88KB, 1-page PDF. Screenshot confirms: full-width dark navy header (edge-to-edge, eyebrow + title + subtitle), clean body content at full page width with navy-blue uppercase section headings, full-width dark navy footer pinned to bottom. No blank pages. No narrow column. No duplicate title. |

---

### BUG-023: Execution deadlock when LLM plan steps reference non-existent dependency IDs

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | High (work order permanently blocked, no output produced) |
| Status | Fixed |
| Files | `server/pocketflow.ts` (`getReadySteps`, `nodePlanSteps`) |
| Symptom | Work order blocked with "Execution Deadlock — No executable steps and not all steps complete — possible dependency deadlock". No output produced. Plan had multiple steps but none were ever ready to execute. |
| Root Cause | `getReadySteps` evaluated `dep && dep.status === "completed"` — if a dep ID doesn't exist in the plan (`dep` is `undefined`), expression returns `false`, treating the missing dep as unsatisfied. LLMs sometimes generate dep IDs using a different format than the step IDs they also generate (e.g. step ID `"step-2"` but dep reference `"step_2"`), causing all downstream steps to deadlock permanently. |
| Fix | Two changes. (1) `getReadySteps`: changed to `!dep \|\| dep.status === "completed"` — missing dep IDs are now auto-satisfied. (2) `nodePlanSteps` at plan parse time: sanitize each step's `dependencies` by filtering out any dep ID not present in the current step list — removes hallucinated IDs before they enter the execution loop. |

---

### BUG-024: Tier 1 Aiden Quality Review flags "Deliverable is HTML, not a PDF" — `postProcessedFile` not passed

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | High (PDF work orders blocked by quality review despite PDF being generated) |
| Status | Fixed |
| Files | `server/orchestration.ts` (quality review call), `server/llm-client.ts` (`runAidenQualityReview` prompt) |
| Symptom | Aiden Quality Review blocked PDF work orders at Tier 1: "Deliverable is HTML, not a PDF" and "Unable to confirm one-page length without PDF rendering". Score 68%, recommendation: block. |
| Root Cause | `runAidenQualityReview` called with 8 arguments — the 9th optional parameter `postProcessedFile` was never passed. This parameter injects a MANDATORY RULE into the Aiden prompt suppressing all format complaints when a binary was auto-generated. Without it, Aiden correctly identifies the deliverable as markdown/HTML, unaware the post-processor will convert it. Additionally, the MANDATORY RULE text only listed PPTX-specific complaints ("not a PowerPoint binary") — didn't cover PDF phrasings ("not a PDF", "cannot verify page count"). |
| Fix | (1) `orchestration.ts`: added `tier2Result.output?.postProcessedFile ?? null` as 9th arg to `runAidenQualityReview`. (2) `llm-client.ts`: expanded MANDATORY RULE text to explicitly suppress: "deliverable is HTML", "not a PDF", "missing .pdf", "cannot verify page count", and all format/save-location complaints regardless of file type. |

---

### BUG-025: Content duplicated in deliverable — full document appears twice after multi-iteration refine loop

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Severity | High (deliverable quality, operator-visible) |
| Status | Fixed |
| Files | `server/pocketflow.ts` (`nodeBuildResponse`) |
| Symptom | Aiden Quality Review reported "Content duplicated — the full brief appears twice". Work order deliverable contained the entire document repeated verbatim. |
| Root Cause | `accumulatedOutputs` is a `Record<string, string>` keyed by `step.id`. On refinement iterations, `nodePlanSteps` appends new steps with new IDs. Both iteration 1 and iteration 2 step outputs accumulate as separate keys. The general document assembly path (`nodeBuildResponse`, non-PDF, non-HTML) joined ALL values with `contentOutputs.join("\n\n")` — producing the full brief from iteration 1 concatenated with the full brief from iteration 2. |
| Fix | `nodeBuildResponse` general path now uses `dict.stepResults` filtered to `r.iteration === dict.iteration` (the last/current iteration). Only the most recent iteration's step outputs are used for assembly. Falls back to all stepResults if last iteration produced no outputs. Same strategy as PDF path (which already had this fix). |
| Known Limitation | This fix is correct for single-step document WOs and full-rewrite refinements (dominant use case). It does not fully solve multi-step work orders where refinement adds delta-only steps targeting individual artifacts (e.g. revising one of three code files). In that case, iteration 0's untouched artifacts would be dropped. This edge case has not been observed in production. Tagged for proper resolution under ADR-001. |

---

## Architecture Decision Record

### ADR-001: PocketFlow Assembly Strategy — `delta_overlay` deferred to v0.5+

| Field | Detail |
| --- | --- |
| Date | 2026-03-07 |
| Status | **Deferred** — Option A in effect |
| Raised By | CODEX (external review), confirmed by Claude Code |

**Decision:** Keep BUG-025 fix (last-iteration-wins) as the interim assembly strategy. Do not implement `delta_overlay` with artifact identity metadata at this stage (alpha, v0.3.8).

**The architectural problem identified:**

PocketFlow has two incompatible semantics in its current implementation:

- `llmRefine()` uses **delta semantics** — plans only new steps to fill gaps, explicitly does not redo completed work.
- `nodeBuildResponse()` (post BUG-025) uses **latest-iteration-wins** — only last iteration's outputs are assembled.

These cannot both be correct for multi-artifact outputs. If refinement is delta-only, assembly must support overlay/merge. If assembly is latest-only, refinement must produce full replacement outputs.

**Correct long-term architecture (tagged for v0.5+):**

Formalize `delta_overlay` contract. Add to `PlanStep`:

- `artifact_key` — stable identity across iterations (e.g. `document.main`, `styles.css`, `app.js`)
- `refine_mode` — `replace` | `supplement` (defer `patch`)
- `target_artifact_key` — required when `refine_mode = patch`

Assembly rule: build a map keyed by `artifact_key`, traverse step results in execution order, apply `replace`/`supplement` rules. Final deliverable produced from resolved artifact map, not raw step concatenation.

**Acceptance tests to implement when this is built (from CODEX):**

1. Single-step document, no refinement → one final document
2. Single-step document, full-rewrite refinement → only refined document, no duplication
3. Multi-step code, no refinement (HTML + CSS + JS) → all three artifacts preserved
4. Multi-step code, delta refinement on one file → original HTML + revised CSS + original JS
5. Multi-step document pack, supplement refinement → main brief + appendix, not just appendix
6. Patch refinement on config → patched config, not patch text concatenated with original
7. Mixed artifacts with intermediate metadata outputs → planning/status text excluded

**Why deferred:** Alpha stage, single-user, dominant use case is single-step document WOs. Edge case (multi-step + delta refinement) not yet observed. Proper implementation requires LLM prompt changes + data model changes + assembly rewrite — better scoped as a planned feature than an ad-hoc fix.

---

## Session 8 — IWO2 Hardened Init (2026-03-08)

App version: v0.8.0 → IWO2 init (commit `348af40`, `6592929`)

### BUG-026: Unguarded `/api/images` routes — authentication bypass

| Field | Detail |
| --- | --- |
| Severity | **Critical** (P0 security) |
| Component | `server/routes.ts` — image upload/retrieval endpoints |
| Root Cause | `GET /api/images/:placeholderId` and `GET /api/images/:placeholderId/meta` routes were registered without the `isAuth` middleware, allowing unauthenticated access to any uploaded image by guessing the placeholder ID. |
| Fix | Added `isAuth` middleware to both routes. Commit `6592929`. |
| Verification | `security.test.ts` — P0 gate test confirms auth-protected image endpoints. |

---

## Session 9 — v0.9.2 / v0.9.5 Release (2026-03-13 / 2026-03-14)

App version: v0.9.2, then v0.9.5 (commits `d56957a`, `4c40fe2`, `817b76b`)

### BUG-027: Dashboard/detail work order status out-of-sync

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Component | `client/src/pages/work-order-detail.tsx` |
| Root Cause | The work order detail view used `staleTime: Infinity` (inherited from global React Query config) and polling that stopped on any non-processing status. The dashboard page overrode `staleTime: 5000` explicitly. After a WO completed, the detail page showed stale "processing" status while the dashboard showed "completed". |
| Fix | Set `staleTime: 3000` on both order and logs queries. Added `refetchOnMount: "always"` so navigating in always fetches fresh data. Added fallback `refetchInterval` of 10s (order) / 15s (logs) for non-processing states so completed/blocked orders self-correct without manual refresh. Commit `4c40fe2`. |

### BUG-028: Standalone workflow output silently dropped — never reached Sandbox

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Component | `server/orchestration.ts` — `handleWorkflowCompletion()` |
| Root Cause | `fileWorkOrderOutput()` was gated behind `if (execution.workOrderId)` with no `else` branch. When a workflow execution had no parent work order (`workOrderId: null`), the completed deliverable was silently dropped — never reaching the Sandbox for preview/download. |
| Fix | Added a create→update two-step that fires after executive review approval for any HTML/code deliverable, regardless of whether a work order is attached. Commit `817b76b`. |

### BUG-029: Contract drift — workflow PM completion writes to wrong fields

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Component | `server/orchestration.ts`, `server/workflow-pm.ts`, `shared/schema.ts`, `server/llm-client.ts` |
| Root Cause | After the schema was refactored to use `tier2Result` (a structured JSON object), the workflow PM completion path still wrote to legacy `result` and `deliverableType` fields that no longer existed on the schema. Additionally, synthetic `WorkOrder` and `Tier1Result` objects passed to helper functions did not match the actual schema shape — missing required fields, wrong types. This caused 17 TypeScript compilation errors. |
| Fix | (1) Workflow PM completion now writes to `tier2Result` with proper structure. (2) Synthetic WorkOrder shapes aligned to actual schema (all required fields present). (3) Synthetic Tier1Result aligned to actual Zod schema. (4) `toolsUsed` added to `Tier2Result` type definition. (5) `gccMemory` exposed in work order insert schema so operators can set GCC on creation. All 17 TS errors resolved, 50/50 tests pass. Embedded in release commit `d56957a`. |
| Related | CODEX review 5.4 identified this contract drift. |

### BUG-030: EXECUTE_WORKFLOW chat action JSON sanitization

| Field | Detail |
| --- | --- |
| Severity | **Medium** |
| Component | `server/routes.ts` — chat action EXECUTE_WORKFLOW handler |
| Root Cause | When Aiden emitted an `<!-- AIDEN_ACTION:EXECUTE_WORKFLOW:{...} -->` block in chat, the LLM sometimes hallucinated trailing `}}` instead of `}` at the end of the JSON payload, causing `JSON.parse()` to fail silently. The workflow was never created but no error was surfaced to the operator. |
| Fix | Added JSON sanitization loop: strips trailing `}` characters while the string is invalid JSON (using `isValidJson()` helper). The action block is also always stripped from the visible reply, even if workflow creation fails. Embedded in release commit `d56957a`. |

### BUG-031: `toolsUsed` missing from Tier2Result type

| Field | Detail |
| --- | --- |
| Severity | **Medium** |
| Component | `server/llm-client.ts` — `tier2ResponseSchema` |
| Root Cause | PocketFlow populated `toolsUsed` on the Tier 2 result, but the Zod schema defining `Tier2Result` did not include `toolsUsed`. This caused TypeScript errors when accessing the field and meant the data was silently stripped during validation. |
| Fix | Added `toolsUsed: z.array(z.any()).optional()` to `tier2ResponseSchema`. Embedded in release commit `d56957a`. |

### BUG-032: `gccMemory` blocked on work order insert schema

| Field | Detail |
| --- | --- |
| Severity | **Low** |
| Component | `shared/schema.ts` — `insertWorkOrderSchema` |
| Root Cause | The insert schema for work orders omitted `gccMemory` via `.omit()`, preventing operators from setting initial GCC context when creating a work order through the API. This blocked the reopen flow from carrying forward accumulated GCC state. |
| Fix | Removed `gccMemory` from the `.omit()` list in `insertWorkOrderSchema`. Embedded in release commit `d56957a`. |

### BUG-033: LLM client — no timeout or retry configured

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Component | `server/llm-client.ts` — `callOpenAICompatible()`, `callAnthropic()`, `chatWithAiden()` |
| Root Cause | Both the OpenAI and Anthropic SDK clients were instantiated without timeout or retry settings. A hung LLM call (e.g., during PocketFlow quality review) would block the work order indefinitely — the step would stay "running" with output present but the PM review never completed. This was the root cause of the known issue documented in CLAUDE.md ("PocketFlow quality review LLM call can hang mid-step"). |
| Fix | Added `timeout: 45000` (45s) and `maxRetries: 1` to all three client instantiation points (OpenAI-compatible, Anthropic, and chat-with-Aiden Anthropic). Embedded in release commit `d56957a`. |

### BUG-034: Orphan recovery — incomplete field cleanup

| Field | Detail |
| --- | --- |
| Severity | **Medium** |
| Component | `server/orchestration.ts` — `recoverOrphanedProcessingOrders()` |
| Root Cause | When the startup orphan recovery detected stale "processing" orders (>10 min), it set `status: "failed"` but did not clear the new watchdog fields (`processingAttemptId`, `heartbeatAt`, `processingStartedAt`). This left ghost ownership data on the recovered order, potentially confusing the runtime watchdog when it started its sweep cycle. |
| Fix | Added `processingAttemptId: null`, `heartbeatAt: null`, `processingStartedAt: null` to the recovery update. Embedded in release commit `d56957a`. |

---

## Session 10 — v0.9.5 Hotfixes (2026-03-14)

App version: v0.9.5 (commits `e1f082c`, `2824869`)

### BUG-035: HTML output threshold too strict — valid HTML rejected

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Component | `server/pocketflow.ts` — `selectBestHtmlOutput()` (line ~809) |
| Root Cause | `selectBestHtmlOutput()` used a score threshold of 80 to determine whether a step output was "real HTML." However, valid HTML documents with proper `<head>` and `<body>` structure scored only ~60 (presence of both tags + basic structure = 60 points, with bonus points for `<!DOCTYPE>`, `<style>`, etc.). This caused the function to return `null` for valid HTML, falling through to raw text assembly which produced broken output. |
| Fix | Lowered threshold from 80 to 40. A score of 40+ reliably indicates real HTML content (any document with `<html>`, `<head>`, or `<body>` tags). Commit `e1f082c`. |
| Trigger | Observed after v0.9.5 release: workflow-produced HTML pages were being delivered as raw markdown/text instead of rendered HTML. |

### BUG-036: Chat workflow silent failure — advanceWorkflowExecution error lost

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Component | `server/routes.ts` — EXECUTE_WORKFLOW chat action handler (line ~3504) |
| Root Cause | After creating the workflow template, steps, execution, and parent work order, the handler called `advanceWorkflowExecution()` inside a `setImmediate()` callback. If the advance failed (e.g., sub-agent LLM misconfigured, step assignment error), the error was caught by `console.error` only — the parent work order remained in "processing" status indefinitely, and the operator saw no indication of failure. |
| Fix | Wrapped the `setImmediate` callback with try/catch that: (1) syncs the parent work order status to "failed", (2) writes an execution log entry with the error details, (3) catches and logs any secondary errors during status sync. Commit `e1f082c`. |

### BUG-037: Deployment-type steps overwrite content deliverable in PM assembly

| Field | Detail |
| --- | --- |
| Severity | **Critical** |
| Component | `server/orchestration.ts` — `handleWorkflowCompletion()`, `server/workflow-pm.ts` — `pmAssembleWorkProduct()` |
| Root Cause | When a multi-step workflow completed, `pmAssembleWorkProduct()` received all step outputs equally. Deployment sub-agents (e.g., Paul/Polaris) produce operational reports ("Deployed to Sandbox, URL: ...") as their step output. Because the PM treated all steps as content, the deployment report was blended into — or even replaced — the actual content deliverable (e.g., a presentation deck's content was replaced by Paul's deployment confirmation). This was visible in Gamma-produced PPTX where the slides contained deployment metadata instead of the requested content. |
| Fix | Three-part fix across two files: (1) In `handleWorkflowCompletion()`, look up each completed step's sub-agent type via `storage.getSubAgent()`, tag deployment-type agents as `role: "metadata"` and all others as `role: "content"`. (2) In `pmAssembleWorkProduct()`, updated function signature to accept role-annotated step results. Content steps go to the PM for assembly; metadata steps are passed as informational context only, with explicit instructions NOT to blend them into the deliverable body. (3) Updated all three assembly paths (LLM assembly, LLM fallback, error fallback) to filter `role !== "metadata"` from content concatenation. Commit `2824869`. |
| Trigger | Gamma PPTX generated from a workflow showed Paul's deployment report in the slides instead of Mark's researched content. |

---

## Session 11 — Gamma PPTX Remediation + Workflow Post-Processing (2026-03-15)

App version: v0.9.5

### BUG-038: Gamma PPTX generation accepts weak slide content and closes without deck-quality safeguards

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Status | **Fixed** (2026-03-15) |
| Components | `server/pptx-quality.ts` (new), `server/pocketflow.ts`, `server/llm-client.ts`, `server/done-contract.ts`, `server/workspace-filing.ts`, `server/orchestration.ts` |
| Symptom | Gamma-backed PPTX work orders can complete with technically valid `.pptx` output that is visibly poor: overlapping text, weak slide pacing, sparse or collision-prone layouts, and confusing operator preview behavior in Sandbox. |
| Root Cause | Four upstream/downstream weaknesses unrelated to the Done Contract: (1) No preflight validation — any markdown, including prose blobs, empty shells, and raw JSON, was sent directly to Gamma. (2) No post-Gamma structural verification — "file exists" was the only success check. (3) Aiden quality review was biased toward content text and could not evaluate slide-presentation fitness. (4) Sandbox preview showed markdown deliverable labeled as "Document preview" for PPTX work orders, confusing operators. |
| Fix | Six-part remediation per `AIDEN_IWO2_GAMMA_PPTX_REMEDIATION_EXECUTION_PLAN_v0.1.0.md`: (1) **Preflight validator** (`server/pptx-quality.ts:validatePptxPreflight`) — rejects empty, too-short, JSON, placeholder, unsegmented prose, and escaped-newline content before Gamma; checks contract slide range and required sections. (2) **Contract parser** (`parseContentContract`) — extracts `minSlides`, `maxSlides`, `requiredSections`, `maxBulletsPerSlide` from contentContract text. (3) **Post-Gamma compliance** (`checkGammaCompliance`) — verifies file existence, size, MIME consistency, estimates slide count vs contract range. (4) **PPTX review supplement** (`buildPptxReviewSupplement`) — injects preflight/compliance/contract evidence into Aiden quality review prompt so LLM can reject weak presentation-quality source even when a binary exists. (5) **Done Contract compliance gate** — Gamma compliance hard failures block `completed` status. (6) **Preview labeling** — PPTX/PDF work orders now show "Source Preview" sandbox label with description noting final deliverable is a .pptx/.pdf file. |
| Files Changed | `server/pptx-quality.ts` (new, 310 lines), `server/pocketflow.ts` (preflight gate + compliance check + result propagation), `server/llm-client.ts` (PPTX supplement parameter), `server/orchestration.ts` (supplement construction + compliance evidence passthrough), `server/done-contract.ts` (gammaComplianceOk gate), `server/workspace-filing.ts` (source_preview type + PPTX labeling), `server/__tests__/pptx-quality.test.ts` (new, 28 tests) |
| Verification | 208 tests pass across 8 test files. Preflight rejects: empty, short, JSON, TODO/placeholder, prose blob, escaped newlines, below-contract slide count, missing required sections. Compliance rejects: missing file, suspiciously small file. Done Contract blocks PPTX completion on Gamma compliance hard failures. Candidate review still blocks even with good compliance. Sandbox labels distinguish source preview from final artifact. |
| Residual Risk | (1) Post-Gamma slide count is estimated from source markdown, not parsed from the binary PPTX — real slide count may differ from Gamma's auto-layout decisions. Phase 2 could add lightweight PPTX binary parsing via python-pptx. (2) Rendered visual quality (overlapping text, layout collisions) is not directly measurable without screenshot-based scoring — preflight catches the source-quality root cause but cannot guarantee Gamma's layout engine renders well. (3) Content contract parsing is heuristic and tolerant — malformed contracts fall back to generous defaults. |
| Execution Doc | `AIDEN_IWO2_GAMMA_PPTX_REMEDIATION_EXECUTION_PLAN_v0.1.0.md` |
| Notes | Preserves existing fallback behavior, `candidate_review`, and Done Contract architecture. No DB/schema changes. No pipeline redesign. |

### BUG-039: Workflow-assembled PPTX/PDF work orders never produce a binary when no step generates one

| Field | Detail |
| --- | --- |
| Severity | **Critical** |
| Status | **Fixed** (2026-03-15) |
| Components | `server/orchestration.ts`, `server/pocketflow.ts` |
| Symptom | A PPTX workflow ("WF: Klear.ai EWC Intro Deck") completed all 4 steps, PM assembled the work product, but no `.pptx` binary was generated. The Done Contract correctly blocked completion ("PPTX binary missing"), operator had to HITL override, and the artifact was filed as HTML/markdown only — no PPTX on the platform or in Gamma. |
| Root Cause | `handleWorkflowCompletion()` scanned step runs for a `postProcessedFile` (line 1843), but when no step produced one (TOM's PocketFlow ran with LLM disabled and produced a prose report instead of slide markdown), the assembled work product was sent to `completeAndFileWorkOrder()` with no binary. There was **no fallback mechanism** to run PPTX/PDF post-processing on the PM-assembled deliverable. The gap: individual step PocketFlow runs call `nodePostProcess()` for format conversion, but the PM work product assembly has no equivalent post-processing step. |
| Fix | Added `postProcessWorkflowDeliverable()` — an exported function in `server/pocketflow.ts` that runs Gamma or local md-to-pptx/html-to-pdf conversion on a deliverable string, outside PocketFlow's SharedDict context. Wired into **both** workflow completion paths in `server/orchestration.ts`: (1) exec-approved path (PM assembly → Aiden approval → completion) and (2) revise-fallback path (revisions exhausted → best-effort completion). The function activates only when: (a) no step already produced a `postProcessedFile`, (b) the parent WO title/description requires PPTX or PDF (via `detectRequiredFormatFromText()`), and (c) the assembled work product has content. Also added `detectRequiredFormatFromText()` as an exported standalone format detector that works without a PocketFlow SharedDict. |
| Files Changed | `server/pocketflow.ts` (`postProcessWorkflowDeliverable()`, `detectRequiredFormatFromText()` — ~130 lines), `server/orchestration.ts` (workflow post-process safety net in both completion paths, import wiring) |
| Verification | 208 tests pass across 8 test files. Execution logs for the test WO confirm: Done Contract blocked the WO before the fix ("PPTX binary missing"), and the new code path would produce a log entry "No step produced a PPTX binary. Running post-processing on assembled work product." followed by local md-to-pptx or Gamma conversion. |
| Residual Risk | (1) The workflow post-processing fallback does not have access to per-workflow Gamma template keys — it uses global settings or no Gamma. Full workflow-template Gamma resolution would require reading the workflow template's `gammaTemplateKey` in the fallback path (not done in this pass to keep the fix minimal). (2) If the assembled work product is poor-quality markdown (e.g., TOM produced a prose report), the local md-to-pptx conversion will produce a low-quality deck — the BUG-038 preflight validator mitigates this by rejecting obviously bad input before Gamma, but the local fallback is more tolerant. |
| Notes | Preserves all existing behavior — this is a pure safety net. If any step already produced a binary, it's used as before. No DB/schema changes. |

### BUG-040: Tier 1 sub-agent routing matches wrong agent due to empty-string fuzzy match

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Status | **Fixed** (2026-03-15) |
| Components | `server/orchestration.ts` (`findSubAgent()`) |
| Symptom | Aiden correctly decided `handler: "B04_MKTG"` (Mark, the marketing agent) but dispatched to `A016_Polaris` (Paul, the deployment agent). Paul then blocked the WO because he's a deployment specialist, not a content creator. Repeated overrides all routed to Paul. |
| Root Cause | `findSubAgent()` fuzzy matching split agent names by `/[\s_-]+/` which produced empty strings from trailing spaces in agent names (e.g., `"A016_Polaris ( PAUL PERSONA ) "` has trailing space → split produces `""`). In JavaScript, `"anything".includes("")` returns `true`, so the empty string acted as a **universal match** — every handler word matched every agent. Paul appeared before Mark in the iteration order, so Paul won the tie at score 1.0. |
| Fix | Added `.filter(w => w.length > 0)` to both `nameWords` and `descWords` splits in `findSubAgent()` to remove empty strings before fuzzy scoring. One-line change. |
| Files Changed | `server/orchestration.ts` (line 1060-1061) |
| Verification | 208 tests pass. Manual trace confirms: with the fix, `findSubAgent("B04_MKTG")` returns Mark (score 1.0, both `"b04"` and `"mktg"` match) while Paul scores 0.0 (no matches). |

### BUG-041: Watchdog kills active Gamma PPTX generation due to heartbeat starvation

| Field | Detail |
| --- | --- |
| Severity | **High** |
| Status | **Fixed** (2026-03-15) |
| Components | `server/gamma-client.ts`, `server/pocketflow.ts` |
| Symptom | PPTX workflow WOs fail with "Watchdog: Stuck Detection — No heartbeat for 63s" while Gamma is still actively generating. The WO is killed and set to `failed` even though execution is progressing normally. |
| Root Cause | `HEARTBEAT_STALE_MS` is 60s but Gamma generation can take 60-150s. During the `await generateWithGamma()` call, no heartbeats are emitted because the polling loop inside `gamma-client.ts` doesn't update the WO heartbeat. The watchdog sees 60s of silence and kills the WO. |
| Fix | Added `onHeartbeat` callback parameter to `pollGeneration()` and `generateWithGamma()` in `gamma-client.ts`. Each 5s poll iteration now calls the callback, which updates `heartbeatAt` on the WO via storage. Wired into all three Gamma call sites in `pocketflow.ts`: PPTX nodePostProcess, PDF nodePostProcess, and workflow post-process helper. Keeps the 60s stale threshold for truly stuck WOs while allowing Gamma's full 150s generation window. |
| Files Changed | `server/gamma-client.ts` (onHeartbeat callback in pollGeneration + generateWithGamma), `server/pocketflow.ts` (heartbeat functions at 3 Gamma call sites) |
| Verification | 220 tests pass. Gamma generation >60s will now emit heartbeats every 5s during polling, preventing watchdog false kills. |
| Residual Risk | If Gamma's API itself hangs (no poll HTTP response for >60s), heartbeats will still starve — but that's correct behavior (truly stuck external dependency). |

### BUG-042: Low-quality workflow deliverables auto-complete without operator review

| Field | Detail |
| --- | --- |
| Severity | **Critical** |
| Status | **Fixed** (2026-03-15) |
| Components | `server/orchestration.ts`, `server/done-contract.ts` |
| Symptom | A workflow WO ("WF: Klear.ai Upsell Program Site Creation") completed with status `completed` despite: PM reviewing steps at 0.20 (twice), Aiden executive review scoring 0.40 with recommendation `revise` and identifying "deliverable contains only step metadata, not the final artifact." The operator received a garbage deliverable marked as completed. |
| Root Cause | Two gaps: (1) The revise-fallback path in `handleWorkflowCompletion()` auto-completes with "best effort" when exec review returns `revise` but revisions are exhausted — regardless of how low the score is. A 0.40 score (below any reasonable acceptance threshold) was treated the same as a 0.70 score. (2) The Done Contract's `"other"` artifact class only checked for deliverable presence and filing — it had no score-based quality gate, so any deliverable that existed would pass closeout. |
| Fix | **Defense in depth — two independent gates:** (1) In `handleWorkflowCompletion()` revise-fallback path: if exec review score is below 0.50, route to `awaiting_operator` instead of auto-completing. Logs the escalation with score and issues. (2) In Done Contract `evaluateDoneContract()`: new shared hard-failure check — if `qualityScore` is below 0.50, blocks completion with `"Quality score X.XX is below minimum 0.50 for completion"`. Score is extracted from the most recent quality/exec review execution log for the WO. Both gates produce `awaiting_operator` terminal state so the operator can review and decide. |
| Files Changed | `server/orchestration.ts` (revise-fallback score gate + quality score extraction for Done Contract), `server/done-contract.ts` (qualityScore field on CloseoutContext + shared hard-failure check + terminal state mapping) |
| Verification | The Upsell Program WO (exec review 0.40) would now: (a) be caught by Option 1 in handleWorkflowCompletion and routed to awaiting_operator, and (b) even if it somehow reached completeAndFileWorkOrder, be caught by Option 2 in Done Contract and blocked. |
| Residual Risk | The 0.50 threshold is a constant — not operator-configurable in this pass. Borderline cases (0.48 vs 0.52) are judgment calls. A future enhancement could make this threshold configurable in operational settings. |

---

## Bug Fixes — Session 12: Execution Reliability (2026-03-21)

### BUG-048: PocketFlow options-scope regression (High)

| Field | Detail |
| --- | --- |
| Severity | High |
| Symptom | `ReferenceError: options is not defined` on all `balanced` and `fast` profile PocketFlow runs. `safe` profile unaffected by accident (all flags false, optional chaining short-circuits). GOO2 Website Build Test hit this on every iteration (9/9 failed, convergence 0). |
| Root Cause | `nodeExecStep()` (line 405, module-level function) referenced `options?.promptCompaction` and `options?.batchedSynthesis` — but `options` is a parameter of `pocketflowExecute()` (line 1789), which is a different scope. When execution profiles were wired in (v0.9.7 performance work), the profile flags were passed through `options` to `pocketflowExecute` but consumed inside `nodeExecStep` without propagation. |
| Fix | Added `promptCompaction`, `batchedSynthesis`, `reviewReduction` fields to `SharedDict` interface. Set them from `options` at `pocketflowExecute()` entry (with `false` defaults). Replaced all out-of-scope `options?.` reads in `nodeExecStep` and the main loop with `dict.*` reads. |
| Files Changed | `server/pocketflow.ts` (SharedDict interface, createSharedDict defaults, pocketflowExecute propagation, nodeExecStep reads, main loop eval call) |
| Verification | All three profiles (safe/balanced/fast) compile and run without ReferenceError. 247/248 tests pass (1 pre-existing timezone test). |

### Lifecycle normalization: retry/reopen/repair workflowExecutionId consistency

| Field | Detail |
| --- | --- |
| Severity | Medium |
| Symptom | `retry` and admin `repair retry` did not reset `workflowExecutionId`, leaving stale workflow linkage on the WO. Only `reopen` cleared it. A retry on a workflow-routed WO could re-enter Tier 1 with a stale `workflowExecutionId` from the previous failed run. |
| Fix | Added `workflowExecutionId: null` to both retry (line ~412) and admin repair retry (line ~1041) update calls. Prior workflow executions are marked `superseded_by_retry` for audit. All three lifecycle paths (retry, reopen, repair retry) now behave consistently. |
| Files Changed | `server/routes.ts` (retry endpoint, admin repair retry endpoint) |

### Feature: Deterministic execution-strategy resolver

| Field | Detail |
| --- | --- |
| Type | New feature |
| Purpose | After Tier 1 approval, deterministically decide whether a WO should use direct (single-agent) or workflow (multi-agent template) execution. No LLM, no embeddings — additive scoring on format, category, token overlap, workflow-shaped signals, and explicit agent coverage. |
| Selection threshold | Score >= 8, margin >= 2 over second candidate |
| GOO2 behavior | Falls back to direct execution — the existing Purple GOO template uses Mark+Paul, not Hank+Darla as the WO requested. Explicit agent coverage gate rejects mismatched templates. |
| Double-execution guard | Prevents duplicate active workflows for the same WO |
| Files Created | `server/execution-strategy-resolver.ts` |
| Files Changed | `server/orchestration.ts` (import, resolver call, workflow routing fork, audit logging) |

### BUG-049: Quality review heartbeat starvation (High)

| Field | Detail |
| --- | --- |
| Severity | High |
| Symptom | GOO3 WO killed by watchdog ("No heartbeat for 103s") during Tier 1 quality review + auto-revision handoff. PocketFlow execution completed successfully (BUG-048 fix confirmed working), Aiden quality review ran and scored 0.65, revision was requested — then watchdog killed it. |
| Root Cause | `runAidenQualityReview()` is an LLM call to the Tier 1 provider (Groq/gpt-oss-120b). During this call, no heartbeats are emitted. Combined with the prior PocketFlow execution time, the total gap exceeds the 60s watchdog stale threshold. Same class of bug as BUG-041 (Gamma heartbeat starvation) but in the quality review path. |
| Fix | Added `withWorkOrderHeartbeatGuard(orderId, phase, fn)` helper — starts a periodic heartbeat (15s interval matching existing `HEARTBEAT_INTERVAL_MS`), executes the callback, always clears interval in `finally`. Wrapped both quality review call sites: initial review and revision-loop review. Added explicit heartbeat refresh before revision re-dispatch to close the handoff gap. No watchdog threshold changes. |
| Files Changed | `server/orchestration.ts` (helper + 2 call site wraps + 1 handoff heartbeat + ownership-aware interval) |
| Verification | 248/248 tests pass. Watchdog stale threshold (60s) unchanged. Max revision count (4) unchanged. Truly stuck WOs still fail — the guard only emits heartbeats while the review callback is actively executing and the attempt still owns the WO. |

### BUG-050: Zombie attempt continuation after watchdog invalidation (High)

| Field | Detail |
| --- | --- |
| Severity | High |
| Symptom | GOO4 watchdog killed the WO at 14:23:23 (10-min ceiling), but the `processWorkOrder` function continued running for 6+ more minutes — dispatching revisions 2 and 3, running quality reviews, and executing PocketFlow steps. The zombie could have overwritten the watchdog's `failed` status with `awaiting_operator` or `completed`. |
| Root Cause | `processWorkOrder` never checks `isAttemptStillOwner()` between revision cycles. The existing `HeartbeatEmitter` class checks ownership on heartbeat ticks, but the revision loop itself has no ownership gates. |
| Fix | Added 3 ownership checks at critical boundaries: (1) before revision re-dispatch, (2) after `pocketflowExecute()` returns in revision loop, (3) before terminal-state write (`awaiting_operator` after revisions exhausted). If attempt ownership is lost, the function exits silently. |
| Files Changed | `server/orchestration.ts` (3 `isAttemptStillOwner` guards in revision loop) |

### BUG-051: Watchdog failure reason not materialized on WO/UI (Medium)

| Field | Detail |
| --- | --- |
| Severity | Medium |
| Symptom | GOO4 shows `status: "failed"` with `tier2Result: null` and `bdmMarker: null`. The operator sees "Failed" in the UI with no explanation. The failure reason exists only in execution logs. |
| Root Cause | The watchdog sweep sets `status: "failed"` and `processingAttemptId` but does not write `bdmMarker` or `tier2Result`. |
| Fix | Watchdog now writes both `bdmMarker` (type `watchdog_stuck`, includes reason, heartbeat age, total duration) and `tier2Result` (blocked: true, reason: `Watchdog: <reason>`) when killing a stuck WO. The UI already renders `bdmMarker` for non-blocked statuses. |
| Files Changed | `server/orchestration.ts` (watchdog sweep update) |

### BUG-052: Deterministic hard-ceiling calibration for heavier runs (Medium)

| Field | Detail |
| --- | --- |
| Severity | Medium |
| Symptom | GOO4 hit the 10-min hard ceiling during revision 2 of a 5-page HTML build. The initial PocketFlow + quality review + revision 1 + quality review consumed ~7.5 min, leaving only 2.5 min for revision 2 — not enough. |
| Root Cause | The 10-min ceiling is per-attempt (correct) but does not account for multi-revision cycles or format-heavy deliverables. |
| Fix | Replaced single `MAX_PROCESSING_DURATION_MS` with `resolveProcessingCeiling(order)`. Default: 10 min. Extended (20 min) for: format-heavy (PDF/PPTX/Gamma keywords), multi-page HTML builds (website/multi-page/sandbox keywords), and WOs already in auto-revision (GCC metadata shows revision attempts > 0). The ceiling reason is included in the watchdog failure message. Stale-heartbeat threshold (60s) unchanged. |
| Files Changed | `server/orchestration.ts` (new `resolveProcessingCeiling()` function, watchdog sweep uses per-WO ceiling) |

### BUG-053: Progress-aware soft-timeout routing (High)

| Field | Detail |
| --- | --- |
| Severity | High |
| Symptom | GOO4/GOO6-class WOs that exceed the hard ceiling but are still actively progressing (fresh heartbeat) get labeled `failed`. The operator sees a dead WO when the work was alive and producing output. |
| Root Cause | The watchdog treated ceiling breach identically regardless of whether the work was dead or alive. Both stale-heartbeat and budget-exceeded-with-fresh-heartbeat mapped to `status: "failed"`. |
| Fix | Split the watchdog kill path into two classes: (1) `heartbeatStale === true` → hard fail with `bdmMarker.type = "watchdog_stuck"` (unchanged). (2) `exceededHardCeiling === true` but heartbeat is fresh → soft timeout with `status = "awaiting_operator"`, `bdmMarker.type = "watchdog_budget_exceeded"`, best-known artifact preserved. Both paths invalidate the attempt (zombie protection). Design note: fresh heartbeat is used as an operational proxy for live progress, not as a permanent semantic replacement for true forward-progress detection. |
| Files Changed | `server/orchestration.ts` (watchdog sweep split), `server/__tests__/recovery.test.ts` (updated test expectation) |

### BUG-050 Extension: Main-path ownership guard (High)

| Field | Detail |
| --- | --- |
| Severity | High |
| Symptom | Purple GOO Landing Page1010 completed with `status: "completed"` but `deliverable: 0 chars` and `postProcessedFile: null`. Watchdog had already soft-timeout'd the WO at 22:21, but zombie continued through quality review (approved at 22:29) and wrote `completed` status. |
| Root Cause | BUG-050 ownership guards were only in the revision loop. The main path (PocketFlow → quality review → completion) had no ownership check after `pocketflowExecute()` returned. Zombie bypassed the watchdog invalidation. |
| Fix | Added `isAttemptStillOwner()` check after main `pocketflowExecute()` returns, before quality review and completion. Zombie now exits silently if attempt was invalidated during PocketFlow execution. |
| Files Changed | `server/orchestration.ts` (1 ownership guard on main path) |

### Loop 14 Patches (Medium)

| Field | Detail |
| --- | --- |
| Patch A | 2DO checklist counter: split into "Milestones: X/Y" + "Events: N". Milestone classifier uses regex on summary text. Old misleading mixed ratio removed. |
| Patch B | PPTX content contracts: `cover`, `thank you`, `title slide`, `closing slide`, `q&a` filtered from `requiredSections` by default. Real content sections still enforced. |
| Patch C | Know-How breadcrumb paths: `Workspace > X > Y` normalized to `X/Y`. Folder lookup tries `Workspace/` prefix. Added `content from` as path trigger keyword. |
| Files Changed | `client/src/pages/work-order-detail.tsx`, `server/pptx-quality.ts`, `server/__tests__/pptx-quality.test.ts`, `server/knowhow.ts`, `server/storage.ts` |

---

## Features & Fixes — Session 12b (2026-03-25)

Operator: Darrel Vaughn | Reviewer: Claude Code (Opus 4.6)

### FEAT-004: GitHub Pages Publish Pipeline + Sandbox Publish/Unpublish

| Field | Detail |
| --- | --- |
| Date | 2026-03-25 |
| Type | Feature |
| Status | Shipped |
| Summary | One-click publish HTML deliverables to GitHub Pages. New `server/publish.ts` service pushes artifacts to `purpleicecube/deliverables` repo via GitHub REST Contents API. Schema: `publishedSlug`, `publishedAt`, `publishedUrl`, `publishPolicy` on artifacts table. API: publish, unpublish, list published, sandbox publish. Public route `GET /p/:slug` serves HTML without auth. Sandbox UI: Publish button, Live link, Copy URL, Unpublish with spinner. |
| Files Changed | `server/publish.ts` (new), `server/routes.ts`, `server/storage.ts`, `shared/schema.ts`, `client/src/pages/sandbox.tsx` |

### BUG-053 Hardened: Phase-level timeout for LLM calls

| Field | Detail |
| --- | --- |
| Date | 2026-03-25 |
| Severity | High |
| Status | Fixed |
| Symptom | WOs stuck in "processing" when quality review LLM call hangs despite HTTP-level timeout. |
| Fix | Added `PhaseTimeoutError` class and 90s phase-level timeout to `withWorkOrderHeartbeatGuard()`. Quality review auto-approves on timeout instead of blocking forever. `Promise.race` pattern ensures bounded execution. |
| Files Changed | `server/orchestration.ts` |

### Additional Changes (2026-03-25)

| Field | Detail |
| --- | --- |
| Know-How parser | Label-colon path extraction (Phase 1 added), `normalizePath()` extracted as shared function, broader Phase 3 regex accepting non-`##_` paths, `references in/at/from` trigger. |
| WO detail | Accept and File button for completed WOs with pending artifacts. |
| Submit order | Description max length bumped to 65,000 characters. |
| Files Changed | `server/knowhow.ts`, `client/src/pages/work-order-detail.tsx`, `client/src/pages/submit-order.tsx` |

---

## Bug Fixes — Session 13 (2026-03-27)

Operator: Darrel Vaughn | Reviewer: Claude Code (Opus 4.6)

### BUG-054: Know-How Chat parser fails on natural language folder references (High)

| Field | Detail |
| --- | --- |
| Date | 2026-03-27 |
| Severity | High |
| Status | Fixed, verified |
| Symptom | Chat messages like "Can you tell me what is in the 04_Resources folder" failed to trigger Know-How retrieval. Aiden responded with "I don't have information about a 04_Resources folder" despite the folder existing in the workspace. The user's follow-up "if you use your know how" also failed to trigger retrieval. |
| Root Cause | Three compounding issues in the Know-How parsing pipeline: (1) **Article blindness in Phase 3 regex** (`server/knowhow.ts`): the preposition+path pattern captured everything after the preposition including articles, producing `"the 04_Resources folder"` which failed the `##_` or `/` validation check. (2) **No bare folder detection**: workspace-standard `##_Name` paths (e.g., `04_Resources`) appearing without a preposition were invisible to all 3 parser phases. (3) **Chat trigger regex too narrow** (`server/routes.ts`): the trigger gate did not recognize "know how" or bare `##_FolderName` patterns, so some legitimate messages never reached the parser. |
| Fix | **Universal fix across all `parseContextRequestFromChat` consumers** (Chat + PocketFlow WO fallback): (1) Phase 3 regex: added optional article skip `(?:the/a/an)` between preposition and path capture group. (2) Added Phase 3b: bare `##_FolderName` pattern detection — matches workspace folder references anywhere in the message without requiring a preposition. (3) `normalizePath()`: added trailing noise-word cleanup so captured paths like `"04_Resources folder"` normalize to `"04_Resources"`. (4) Chat trigger regex: added `know-how` and `##_FolderName` patterns so "use your know how" and bare folder names enter the retrieval block. |
| Architecture Note | All fixes are in the shared parser (`knowhow.ts:normalizePath`, `knowhow.ts:parseContextRequestFromChat`) and are inherited by every consumer — Chat handler, PocketFlow WO fallback, and any future consumer that imports `parseContextRequestFromChat`. The Chat trigger regex widening is the only Chat-specific change. **Future consideration (not implemented):** removing the Chat trigger gate entirely and relying solely on the parser's `null` return would eliminate this class of trigger/parser mismatch bugs permanently. |
| Files Changed | `server/knowhow.ts` (`normalizePath`, `parseContextRequestFromChat` Phase 3 + new Phase 3b), `server/routes.ts` (Chat trigger regex) |
| Verified | Parser test: 5 natural-language inputs all produce correct `ContextRequest` with clean paths. API test: `POST /api/knowhow/resolve` with `paths: ["04_Resources"]` returns sources with score 1.0. |

---

## Session 14 — Know-How Chat Retrieval Hardening (2026-03-27 / 2026-03-28)

Operator: Darrel Vaughn | Reviewer: Claude Code (Opus 4.6)

**Note:** Loops 15–20 below are **retrospective normalization** per `LOOP_SOP.md`. Last contemporaneously documented loop: Loop 14 + Addendum (2026-03-21). Full implementation report: `WS006_AIDEN(GLOBAL)/05_Artifacts/IWO2_KNOWHOW_CHAT_RETRIEVAL_IMPLEMENTATION_REPORT_v0.1.0.md`.

### Loop 15: BUG-054 — Know-How Parser Fix (High)

Documented above in Session 13 entry. Parser: article skip, Phase 3b bare folder detection, trigger regex widened.

### Loop 16: FEAT-005 — Folder Directory Listing in Retrieval

| Field | Detail |
| --- | --- |
| Date | 2026-03-27 |
| Type | Feature |
| Summary | New `buildFolderListing()` on KnowHowService. Injects synthetic directory source with child folders, descriptions, and artifact counts into path-targeted retrieval results. Score 1.0. |
| Files Changed | `server/knowhow.ts` |

### Loop 17: FEAT-006 — Universal Text Extraction Service

| Field | Detail |
| --- | --- |
| Date | 2026-03-28 |
| Type | Feature |
| Summary | New `server/text-extractor.ts` — registry-based extraction. PDF (pdf-parse), DOCX (mammoth), PPTX (jszip + XML). Exports `canExtract()`, `extractText()`, `registerExtractor()`. Workspace provider refactored to delegate. `isUnsupportedMime()` calls `canExtract()`. |
| Dependencies | `mammoth` (new) |
| Files Changed | `server/text-extractor.ts` (new), `server/workspace-provider.ts`, `server/knowhow.ts`, `package.json` |

### Loop 18: BUG-055 — Name Search Timeout (High)

| Field | Detail |
| --- | --- |
| Date | 2026-03-28 |
| Severity | High |
| Symptom | Know-How Chat retrieval timed out (>15s) resolving artifact names. Aiden responded "I don't have access." |
| Root Cause | Path-resolution fallback used `searchArtifactsByKeyword` which does `ILIKE` on content column (base64 blobs). |
| Fix | New `searchArtifactsByName()` (name-only ILIKE). New `searchByName()` on WorkspaceProvider interface. Know-How fallback uses name-only search. |
| Performance | 15s timeout → 0.76s (20x speedup) |
| Files Changed | `server/storage.ts`, `server/workspace-provider.ts`, `server/knowhow.ts` |

### Loop 19: BUG-056 — Source-Over-Derivative Scoring (High)

| Field | Detail |
| --- | --- |
| Date | 2026-03-28 |
| Severity | High |
| Symptom | Aiden returned hallucinated statistics from WO-generated summaries instead of actual source document content. |
| Root Cause | WO outputs (work-product.md, Gamma PDFs, auto-summaries) scored identically to original source documents, filling token budget with derivative content. |
| Fix | New `isWoGeneratedArtifact()` detects WO outputs by filing path and name patterns. Score: source docs 1.0, WO derivatives 0.5 (path tier) or x0.6 (keyword tier). Applied universally across all retrieval tiers. |
| Files Changed | `server/knowhow.ts` |

### Loop 20: FEAT-007 — Chat Workspace Awareness + Hardening

| Field | Detail |
| --- | --- |
| Date | 2026-03-28 |
| Type | Feature + hardening |
| Summary | (A) `buildWorkspaceIndex()` — live directory tree in Chat system prompt, refreshed per message. (B) 6-point Workspace Content Rules instructing Aiden to answer from Know-How context, not create WOs. (C) 15s timeout guard on Know-How resolve with logging. |
| Files Changed | `server/routes.ts` |

### BUG-057: Gamma PDF never called — HTML early-exit bypasses post-processing (Critical)

| Field | Detail |
| --- | --- |
| Date | 2026-04-07 |
| Severity | Critical |
| Symptom | Work orders with `gammaTemplateKey: klear_pdf_v1` never triggered Gamma PDF generation. Log repeated: `Deliverable is HTML — skipping PPTX/PDF post-processing.` Zero `gamma_generation_records` written. Sub-agent produced HTML output; `nodePostProcess()` bailed out before reaching the Gamma path. |
| Root Cause | `nodePostProcess()` (pocketflow.ts:1375) had an unconditional HTML early-exit: any deliverable starting with `<!DOCTYPE html` or `<html` returned immediately, regardless of whether a Gamma PDF/PPTX policy was active. The guard was designed for Hank/WebBuilder HTML deliverables but fired for all agents, including Mark producing HTML for PDF work orders. |
| Fix | (A) HTML early-exit now checks `dict.gammaPolicy?.outputFormat` — if Gamma PDF or PPTX is the target, HTML content passes through as Gamma input instead of triggering the bail-out. (B) `gamma-client.ts` fixed hardcoded `.pptx` file extension in download path — now uses `exportAs` to determine correct extension (`.pdf` or `.pptx`). |
| Files Changed | `server/pocketflow.ts`, `server/gamma-client.ts` |

---

## Session — IWO3 Chat Correlation-ID Collision (2026-05-03)

Operator: Darrel Vaughn | Reviewer: Claude Opus 4.7 | Tree: IWO3 (`iwo3/main`)

### BUG-058: Chat-driven WO 409s after clear-history or new session (cross-session correlation_id collision) (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-03 |
| Severity | High (blocks chat-driven WO creation in any second-session attempt at the same message index) |
| Status | Fixed, verified |
| Files | `apps/console-streamlit/views/chat.py` |
| Symptom | Operator submitted *"I need a workorder for a 6 slide introdeck wlcome to Klear.ai"* on `aiden-iwo3.streamlit.app/chat`, picked the `klear_pptx_primary` template from the resolver clarification picker, clicked **Create + run now**, and got back a raw JSON 409 in the chat: `409 — {'error': 'duplicate_correlation_id', 'correlation_id': 'chat:2-run', 'existing_work_order_id': 'f8dda4e3-…', 'existing_title': 'Create 4-slide Intro Deck for Klear.ai'}`. The brief was a brand-new request (different title, different slide count), but the DB rejected it because a prior session at the same message index had already used `correlation_id='chat:2-run'`. |
| Root Cause | `views/chat.py::_promote_reply` built the WO `correlation_id` as `f"chat:{idx}-{action}"` where `idx` is the message-list index. The Beta-1 ε.3 / Q8 partial UNIQUE on `(client_id, correlation_id) WHERE correlation_id LIKE 'chat:%'` was added to prevent fast-double-click duplicates within a single session — but `idx` resets to 0,1,2 every time the operator clears history or starts a new session. Cross-session collisions on the same idx slug were inevitable. The `_handle_action_error` path also rendered the raw 409 JSON with no operator-readable summary. |
| Fix | (A) New `_correlation_id_for_turn(messages, idx, action)` helper builds the correlation_id from `sha1(msg.ts \| idx \| title)[:12]` so the same message in the same session always produces the same hash (idempotency preserved against fast double-clicks) but different sessions / different briefs always get distinct hashes. (B) New `_existing_wo_from_409(detail)` helper extracts `existing_work_order_id` + `existing_title` from the 409 detail (handles both dict and JSON-string shapes). (C) New `_handle_action_error` callback in `_render_actions` detects the `duplicate_correlation_id` 409 specifically, surfaces a friendly warning *"This brief was already submitted as **Title** (`uuid`). Open the existing work order from the buttons below…"*, and appends a status message to the chat with Open-WO action buttons so the operator can navigate to the prior WO instead of seeing a JSON dump. |
| Verified | Smoke-test: `_correlation_id_for_turn` returns same hash for same message+idx (`chat:9a273470b57a-run`) and different hash after ts change (`chat:40229f411e77-run`). `_existing_wo_from_409` parses both `dict` and JSON-string forms; returns None for unrelated 409s. Streamlit smoke 30/5 unchanged. |
| Files Changed | `apps/console-streamlit/views/chat.py` (new helpers + correlation_id call-site update + friendlier error rendering, ~80 lines) |

---

## Session — IWO3 Dashboard Recent-WO Click Auth Loss (2026-05-10)

Operator: Darrel Vaughn | Reviewer: Claude Opus 4.7 | Tree: IWO3 (`iwo3/main`)

### BUG-059: Clicking a Recent Work Order on the Dashboard kicks operator back to login (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-10 |
| Severity | High (blocks the most natural navigation path on the dashboard; every WO click on the live console terminates the operator's session) |
| Status | Fixed, verified |
| Files | `apps/console-streamlit/views/dashboard.py`, `apps/console-streamlit/shell.py` |
| Symptom | Operator on `aiden-iwo3.streamlit.app/dashboard` clicked the row "I Need a PPT based on Klear.ai template in GAMMA" in the Recent Work Orders panel. Browser navigated to `aiden-iwo3.streamlit.app/work_orders?focus=<id>`. Streamlit Cloud responded with a "Page not found" dialog and the page underneath was the public landing/login screen. The operator had to sign in again from scratch. Reproduced on every recent-WO row click. |
| Root Cause | Loop Iota.x dashboard polish (commit `608439d`) wrapped each Recent-WO row in a raw HTML `<a href="/work_orders?focus={id}" target="_self">`. That's a *full browser navigation*, not Streamlit-native in-app routing. Two compounding effects on Streamlit Cloud: (1) the registered `st.Page("views/work_orders.py", title="Work Orders")` has no explicit `url_path`; Streamlit auto-derives the URL — typically `/work-orders` (hyphen), not `/work_orders` (underscore) — so the link's path doesn't match a registered page and Streamlit emits a 404 fallback. (2) Even if the path matched, Streamlit Cloud creates a *new* WebSocket session on a hard browser navigation; the new session has empty `st.session_state`, `iwo3_logged_in` is False, and `Home.py` falls through to `_render_public_router()` (the landing page). Streamlit Cloud preserves session_state across in-app reruns ONLY, never across full URL navigations. The same architectural constraint also affected the panel's "View all →" link at the section-head; it landed on a registered page so the URL itself worked, but it would still drop session_state if exercised. |
| Fix | Replaced the HTML `<a>`-wrapped rows with a Streamlit-native column layout per row. Each row is now `st.columns([5, 1, 1.6])` with: (a) a tertiary `st.button(wo.title, key=f"dash_open_wo_{wo.id}", use_container_width=True, type="tertiary")` in the title column — on click, sets `st.session_state["work_orders_focus_id"] = wo.id` then calls `st.switch_page("views/work_orders.py")` (in-app navigation, preserves session_state); (b) the priority chip in column 1; (c) the status chip in column 2. The "View all →" link was converted to `st.page_link("views/work_orders.py", label="View all →")` — Streamlit's SPA-safe navigation primitive (≥1.30). `views/work_orders.py:398` already reads `session_state["work_orders_focus_id"]` (set at line 398 via `pop`), so the existing focus-resolution UX is unchanged. New CSS in `shell.py` (`.iwo3-wo-row-meta`, `.iwo3-wo-chip-cell`) tightens the meta caption + chip alignment so the row still reads as a polished list item. Fix scope: ~70 lines across 2 files. |
| Verified | Streamlit view-import smoke 25/25 still green; full Streamlit suite 60/5 still green. Manual test path: dashboard → click Recent WO row → switch_page lands on `/work-orders` with the focused WO auto-expanded; `iwo3_logged_in` preserved (no re-login). Hosted verification: Streamlit Cloud auto-redeploy from `iwo3/main` will pick up the fix; operator visual smoke at `https://aiden-iwo3.streamlit.app/dashboard` is the next gate. |
| Files Changed | `apps/console-streamlit/views/dashboard.py` (`_recent_wo_panel` rewrite + docstring with BUG-059 reference, ~50 lines), `apps/console-streamlit/shell.py` (+2 CSS classes, ~20 lines) |
| Related | The pattern "HTML `<a target=_self>` for in-app navigation" should be rejected anywhere in the Streamlit console going forward — same architectural constraint applies to every `<a href="/...">` that points at a Streamlit page. Use `st.switch_page` for click-handler navigation and `st.page_link` for static link affordances. |

---

## Session — IWO3 Loop Xi Recovery Gate Too Narrow (2026-05-10)

Operator: Darrel Vaughn | Reviewer: Claude Opus 4.7 | Tree: IWO3 (`iwo3/main`)

### BUG-060: Loop Xi Edit + Redispatch unreachable from `awaiting_operator` / `blocked` / `deferred` (Medium)

| Field | Detail |
| --- | --- |
| Date | 2026-05-10 |
| Severity | Medium (operator can still recover via a manual status hop, but the trap is invisible — the Recovery panel just hides itself with no explanation, and the natural state to amend a WO from is exactly the state that's blocked) |
| Status | Fixed, verified |
| Files | `apps/api-fastapi/routes/work_orders.py`, `apps/console-streamlit/views/work_orders.py`, `apps/api-fastapi/tests/test_work_orders_xi_route.py` |
| Symptom | Operator on `aiden-iwo3.streamlit.app/work_orders` had a WO `bec65d0e-...` ("I Need a PPT based on Klear.ai template in GAMMA") in `awaiting_operator` after a redispatch. They wanted to attach the Klear template (`klear_pptx_primary`) and re-run, but the Loop Xi Recovery panel did not render the Edit popover on `awaiting_operator` — only Reopen (terminal-only) and the unrelated Transitions picker showed. Operator's only path to amend was: transition `awaiting_operator → processing` first, then Edit, then Save, then Redispatch. The hop was undocumented in-UI and the recovery panel went silent rather than surfacing a "transition first" hint. |
| Root Cause | Loop Xi (commit `caa7c8c`) defined `_EDITABLE_STATUSES = ("pending", "processing")` server-side and `is_active = wo.status in ("pending", "processing")` UI-side. The two-element set was too narrow: `awaiting_operator` (operator-review-required), `blocked` (mid-flight stuck, awaiting human), and `deferred` (decision postponed) are all non-terminal states where operator amendment is operationally useful — those are *exactly* the states from which an operator most often wants to edit + retry. Lock-step gate on both sides meant the operator's natural recovery surface disappeared in the most common amendment scenarios, with no in-UI hint that a transition-first hop was required. The original Loop Xi scope brief (`IWO3_DARKMODE_ONESHOT_SCOPE_REOPEN_EDIT_REDISPATCH_v0.1.0.md`) didn't enumerate every non-terminal status by name; the implementer chose the narrow set defensively, which surfaced as an operator trap on first contact with a real `awaiting_operator` WO. |
| Fix | Universal widening on both sides of the dispatch boundary. Backend `apps/api-fastapi/routes/work_orders.py:_EDITABLE_STATUSES` and `_REDISPATCHABLE_STATUSES` both now equal `("pending", "processing", "blocked", "awaiting_operator", "deferred")` — every non-terminal status. Terminal states (`completed`, `done`, `failed`) still require POST `/reopen` first; `cancelled` remains a deliberately one-way trip. UI `apps/console-streamlit/views/work_orders.py:_operator_recovery_panel` widened `is_active` to the matching set so Edit + Redispatch buttons render in lockstep with the backend gate. The PUT and POST `/redispatch` 409 error payload's `allowed_statuses` field now reflects the wider set, so any future operator who hits a 409 sees the actual current vocabulary in the response. |
| Verified | New parametrized pytest `test_edit_allowed_from_non_terminal_status[blocked\|awaiting_operator\|deferred]` and `test_redispatch_allowed_from_non_terminal_status[...]` lock the widened gate (6 new test cases). Existing `test_edit_blocked_status_rejected` was renamed to `test_edit_completed_status_rejected` because the original name was misleading (it always seeded `completed`, never `blocked`); the assertion still locks the terminal-state-rejection case. Full Loop Xi test suite green: 20/20 (was 14/14). Streamlit smoke 27/27 unchanged. The hosted operator path is now: WO is in any non-terminal state → Edit popover renders → select template → Save → `work_order.edited` audit row appears → click Redispatch → fresh dispatch with the attached template_profile_id. No transition-first hop required. |
| Files Changed | `apps/api-fastapi/routes/work_orders.py` (~15 lines: widen both status tuples + extended docstring with BUG-060 reference), `apps/console-streamlit/views/work_orders.py` (~10 lines: widen `is_active` + docstring note), `apps/api-fastapi/tests/test_work_orders_xi_route.py` (~50 lines: rename misleading test + 2 new parametrized lock-tests covering 6 cases) |
| Related | This addresses the D-Xi-8 ask floated in the Loop Xi handback follow-up. The Recovery panel still hides on terminal states (correct behavior — Reopen is the entry point there). Future polish (separate from this fix): the panel could surface a passive caption like "*Recovery actions are reachable from any non-terminal state. Currently `cancelled`.*" when the panel hides on `cancelled`, so the silence isn't ambiguous. Out of scope for this bug fix. |

---

## Session — IWO3 FFAI Tenant Onboarding + Auth Polish (2026-05-16)

Operator: Darrel Vaughn | Reviewer: Claude Opus 4.7 | Tree: IWO3 (`iwo3/main`)

Cluster of four related bugs surfaced during HITL testing of an FFAI
multi-step PPTX workflow ("Create FFAI PPT Introduction (5 slides)").
BUG-061 was the visible symptom; BUG-062 was the deeper root cause
(seed gap); BUG-063 surfaced once the LLM-layer chain unblocked; BUG-064
surfaced as a follow-on auth-UX issue on the retry attempt.

### BUG-061: PM Tier-1.5 call rejected by Groq with `'messages' must contain the word 'json'` (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | High (blocks every multi-step workflow dispatch that lands on PM Tier-1.5 — both tenants) |
| Status | Fixed, verified |
| Files | `apps/api-fastapi/runtime/tier_1_5_pm.py`, `apps/api-fastapi/tests/test_tier_1_5_pm_groq_json_guard.py` |
| Symptom | Operator submitted "Create FFAI PPT Introduction (5 slides)" via Chat with Aiden on `localhost:8504/chat`. Aiden classified it as a multi-step workflow and dispatched to PM. Chat surface rendered: `pm_failed: response_invalid: groq returned HTTP 400: {"error":{"message":"'messages' must contain the word 'json' in some form, to use 'response_format' of type 'json_object'.","type":"invalid_request_error"}}`. WO was created but stuck at the PM dispatch boundary. |
| Root Cause | Groq's API guard for `response_format: {"type": "json_object"}` requires the literal substring `json` (case-insensitive) in at least one of the request messages. PM's `tier_1_5_pm.py:_invoke_pm_for_workflow` sets that response_format on every call, but: (1) the user_message is `json.dumps({...})` — produces JSON *syntax* but not the literal word "json"; (2) the system prompt comes from `cfg.system_prompt or PM_SYSTEM_PROMPT` — `PM_SYSTEM_PROMPT` (the module fallback) does mention "JSON", but `cfg.system_prompt` from the DB row often does not (Klear's seeded 5650-char `pm_tier_15` prompt has zero matches for "json"). So either tenant could hit the guard. FFAI hit it through a different path (BUG-062 fallback). Tier-1 Aiden and Tier-2 sub-agents weren't vulnerable: both have dedicated output-schema constants that always include the word "JSON" by construction. |
| Fix | Prepended a one-line lead-in to PM's `user_msg` that always contains the literal word "JSON", before the `json.dumps(...)` payload: `user_msg = "Respond strictly as a JSON object matching the schema described in the system prompt. Inputs follow:\n" + json.dumps({...})`. This satisfies the Groq guard regardless of which `system_prompt` the resolver returned and regardless of tenant. Added explanatory comment block referencing BUG-061 and BUG-062 so future readers understand why this defensive belt exists. |
| Verified | New regression suite `test_tier_1_5_pm_groq_json_guard.py` — 3 tests: (a) source contains the lead-in string after the fix; (b) `response_format: json_object` is still the default (if it ever flips, the lead-in becomes vestigial and should be removed in the same change); (c) `PM_SYSTEM_PROMPT` continues to mention JSON. All 3 pass. Live: FFAI WO retry post-fix passed the Groq validator on the next attempt. Full health/system-checks/PM test sweep: 8/8 passed. |
| Files Changed | `apps/api-fastapi/runtime/tier_1_5_pm.py` (~10 lines: user_msg lead-in + rationale comment), `apps/api-fastapi/tests/test_tier_1_5_pm_groq_json_guard.py` (~50 lines: new regression suite) |
| Related | Defensive belt — even if BUG-062 (FFAI seed gap) is closed and Klear's custom `pm_tier_15` prompt is later rewritten to mention JSON, this lead-in stays as a belt against any future tenant authoring a custom prompt that omits the word. |

### BUG-062: FFAI tenant missing `pm_tier_15` + 9 Tier-2 `llm_configs` rows (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | High (every multi-step FFAI workflow silently falls back to FFAI's `aiden_tier_1` config for the wrong role — produces structurally wrong responses + incidentally triggers BUG-061) |
| Status | Fixed, verified |
| Files | `db/seeds/llm_configs.json` (seed data); side-effect at `apps/api-fastapi/llm/config_resolver.py:78` (fallback path) |
| Symptom | While triaging BUG-061, DB inspection showed `llm_configs` had 11 rows for Klear (`aiden_tier_1` + `pm_tier_15` + 9 Tier-2 sub-agent roles) but only 1 row for FFAI (`aiden_tier_1`). When PM or any Tier-2 role was invoked for FFAI, `resolve_llm_config()` found no direct row and fell back to FFAI's `aiden_tier_1` config (`TENANT_DEFAULT_ROLE` = `aiden_tier_1`). That config's provider, model, credentials, and `system_prompt` are all Aiden's — so the LLM received an Aiden system prompt and was expected to behave as PM or Tom or Mark. |
| Root Cause | The seed file `db/seeds/llm_configs.json` shipped a complete role catalog for Klear (11 rows) but only the bootstrap `aiden_tier_1` row for FFAI. The `config_resolver` fallback to `TENANT_DEFAULT_ROLE=aiden_tier_1` is correct *as a safety net* but silently substitutes the wrong system_prompt for non-Aiden roles. There was no seed-contract enforcement that "every tenant must have a row for every canonical role." Also, the existing FFAI `aiden_tier_1` seed row had `displayName: null` which would trip a NOT NULL constraint on a fresh reseed. |
| Fix | (A) Cloned Klear's 10 non-Aiden role rows onto FFAI in `db/seeds/llm_configs.json` (same providers, models, credentials, options, system_prompts — this is the *baseline*; per-tenant customization happens via the Sub-Agents UI later). ID series: `000091000020`–`000091000029` (kept distinct from Klear's `000091000001`–`000091000011`). (B) Applied the same 10 rows to the live `aiden_iwo3` Postgres via parameterized asyncpg INSERTs so the fix takes effect immediately without a full reseed (which would risk wiping operator state). (C) Patched the pre-existing FFAI `aiden_tier_1` seed row to include `displayName: "Aiden Tier 1"` + `description` so future reseeds don't trip the NOT NULL. |
| Verified | DB count: `SELECT COUNT(*) FROM llm_configs WHERE client_id = FFAI` returns 11 (was 1). `/system/checks` for FFAI now reports `LLM Provider: passed=true, detail: "11/11 configs have credentials present"`. `resolve_llm_config(client_id=FFAI, agent_role='pm_tier_15')` returns `source="role"` (was `source="tenant_default"`). |
| Files Changed | `db/seeds/llm_configs.json` (+10 rows for FFAI + patched aiden_tier_1 displayName), live `aiden_iwo3` DB (10 INSERTs via asyncpg) |
| Related | Long-term, the seed contract should enforce "every tenant must have a row for every canonical role" — that's an ADR-worthy decision for a follow-up loop. The `config_resolver` fallback semantics (`TENANT_DEFAULT_ROLE=aiden_tier_1`) are still in place; for PM and Tier-2 roles, falling back to Aiden's system_prompt is rarely correct — a follow-up could make the fallback use the module-level `*_SYSTEM_PROMPT` instead of `cfg.system_prompt` when `cfg.source == 'tenant_default'`. Captured here for triage, not implemented in this fix. |

### BUG-063: FFAI tenant missing Gamma `adapter_credentials` row — `credential_missing` blocks render (Medium)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | Medium (FFAI cannot dispatch any Gamma render; blocks the same end-to-end PPTX flow that BUG-061+062 unblocked at the LLM layer) |
| Status | Fixed (TEMPORARY stand-in — see Cutover plan below), verified |
| Files | `adapter_credentials` table; affects `apps/api-fastapi/routes/adapter_credentials.py` `get_adapter_status` 4-state resolution |
| Symptom | `/system/checks` Gamma row for FFAI returned `passed=false, detail="no adapter_credentials row for this tenant"`. `/adapter_status/gamma` for FFAI returned `status: "credential_missing"`. Any FFAI WO that reached Paul's deliver step with a `gamma_*` output kind would fail at dispatch. |
| Root Cause | Not a code bug — operator-setup gap. Klear has a seeded `adapter_credentials` row pointing at `GAMMA_REGISTRY_TEST_KEY` env var with `first_invocation_confirmed_at` populated (operator-acknowledged the Loop 9 dual gate). FFAI was never onboarded to Gamma, so no row existed — the live Gamma adapter's two-gate check returned `credential_missing` and dispatch failed. Operator decision: temporarily share Klear's Gamma account as a stand-in until FFAI provisions its own. |
| Fix | Inserted one `adapter_credentials` row for FFAI mirroring Klear's row exactly: same `credential_ref` (`credential_ref:env:GAMMA_REGISTRY_TEST_KEY`), same `adapter_catalog_id` (Gamma), `first_invocation_confirmed_at` stamped to `now()` so the dual gate passes immediately (operator-acknowledged as a stand-in), `notes` clearly marked **TEMPORARY STAND-IN** with the cutover condition spelled out. Explicitly NOT cloned (per operator instruction): `template_profiles` rows — FFAI's branded Gamma PPTX/PDF templates will be added separately when the FFAI team supplies them. Until then, FFAI Gamma renders will use Gamma's platform defaults, not Klear's branded templates. `client_adapter_configs` rows were already present for both tenants (seed-time) and were not touched. |
| Verified | `/adapter_status/gamma` for FFAI returns `status: "live_confirmed"` with `credential_id` populated and the TEMPORARY note attached. `/system/checks` Gamma row for FFAI returns `passed: true, detail: "live gate + credential row present"`. `all_passed: true` for FFAI across all 5 checks. |
| Files Changed | Live DB: 1 row inserted into `adapter_credentials` (id `7e87f707-c99e-4265-88ad-fbbf2952bbae`). No code change. No seed file change (`adapter_credentials.json` does not exist — credentials are runtime-write artifacts, not seed data; reseeding does not truncate this table). |
| Related — Cutover plan when FFAI provisions its own Gamma account | (1) Provision an FFAI-owned Gamma API key; add to env (e.g. `GAMMA_FFAI_KEY`) on every host (local + Railway). (2) `UPDATE adapter_credentials SET credential_ref = 'credential_ref:env:GAMMA_FFAI_KEY', notes = '<new note>', updated_at = now() WHERE id = '7e87f707-c99e-4265-88ad-fbbf2952bbae'`. (3) Optionally reset `first_invocation_confirmed_at` to NULL so the operator must reconfirm via the Sub-Agents/Adapter UI on first use. (4) Once verified live, remove this BUG-063 entry's TEMPORARY status. FFAI default `template_profiles` for Gamma (PPTX + PDF, with FFAI branding) are intentionally absent and need to be added later — track separately when the FFAI team supplies the templates. |

### BUG-064: Streamlit chat JWT auto-refresh missing — `API error 401 invalid_token/expired` forces sign-out (Medium)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | Medium (every operator hits this once the access-token TTL elapses; only pre-fix escape was a full sign-out/sign-in) |
| Status | Fixed, verified |
| Files | `apps/console-streamlit/api_client.py`, `apps/console-streamlit/Home.py`, `apps/console-streamlit/shell.py` |
| Symptom | After the BUG-061/062/063 fix sweep, a follow-up "Lets try that again" message on the same chat session returned: `❌ API error 401: {'error': 'invalid_token', 'kind': 'expired'}`. Chat surface also rendered the warning: `💡 Cross-session persistence offline — chat will not be saved when you refresh. Verify the FastAPI runtime is reachable and you have client:read.` Operator had no recovery path short of signing out and back in. |
| Root Cause | The FastAPI `/auth/login` route returns both access_token and refresh_token; `/auth/refresh` works correctly. But the Streamlit `ApiClient` was never given the refresh_token at construction time, and its `_request` method had no 401 handling. So when the access token expired, every subsequent request returned HTTP 401 with `{"error": "invalid_token", "kind": "expired"}` and `_request` surfaced the 401 verbatim via `APIError`. Each view rendered the raw error string with no recovery path. The refresh_token *was* stored in `st.session_state["iwo3_refresh_token"]` (used by `logout` only) but was never passed to the client. |
| Fix | Three coordinated edits across the Streamlit console: (1) `api_client.py` — `ApiClient.__init__` gains `refresh_token` parameter; new `set_refresh_token()` setter; new `_try_refresh_access_token()` helper that POSTs to `/auth/refresh` and rotates the bearer header in place; `_request` detects the specific `{"error":"invalid_token","kind":"expired"}` 401 shape via `_is_expired_401()` and retries the original request **once** after a successful refresh. A `_retry` guard prevents infinite loops if the retried request still 401s for a non-expiry reason. (2) `Home.py` — `_set_jwt_session` now passes `refresh_token=refresh_token` to the `ApiClient` constructor so login-time clients have the refresh token from the first request. (3) `shell.py` — `page_requires_api()` self-heals pre-fix session state: if an existing ApiClient in `st.session_state['iwo3_api']` has no `_refresh_token` but `st.session_state['iwo3_refresh_token']` is set, hydrate the client from session state on the next render. This means operators already signed in when the fix landed do NOT need to sign out + back in. |
| Verified | Live login → `_try_refresh_access_token()` returns True, bearer header rotates, subsequent `/tenants` succeeds against real data. Auto-retry test: bogus bearer → 401 → refresh fires → retry succeeds with real data (proves the retry branch wiring is correct end-to-end). Streamlit view-import smoke: 27/27 pass. |
| Files Changed | `apps/console-streamlit/api_client.py` (~60 lines: refresh_token field + setter + refresh helper + 401-detection helper + retry branch), `apps/console-streamlit/Home.py` (~5 lines: pass refresh_token at JWT login), `apps/console-streamlit/shell.py` (~10 lines: self-heal session state in page_requires_api) |
| Related | Refresh tokens are not rotated on use in Beta-1 (intentional). If the refresh token itself expires (longer TTL than access), the operator is forced to sign in again — expected behavior, not a bug. A future loop could add a `auth.session_refreshed` UI affordance (small badge or toast) so operators see when a transparent refresh fires; skipped here because BUG-064's goal is invisible recovery. |

### BUG-065: PM step_plan validation fails when tenant `system_prompt` doesn't include the output-schema contract (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | High (blocks every multi-step workflow dispatch on any tenant that has customized `llm_configs.system_prompt` for `pm_tier_15` without re-including the strict step_plan schema — Klear is the canonical case; FFAI inherits the same problem via the BUG-062 clone) |
| Status | Fixed, verified |
| Files | `apps/api-fastapi/runtime/tier_1_5_pm.py`, `apps/api-fastapi/tests/test_tier_1_5_pm_groq_json_guard.py` |
| Symptom | After BUG-061 / BUG-062 / BUG-063 / BUG-064 fixes, retrying the FFAI "Create FFAI PPT Introduction (5 slides)" workflow chat surfaced a new error: `pm_failed: plan_malformed: step_plan must be a list of 4 entries; got None`. PM's Groq call succeeded (BUG-061 held); the LLM returned a JSON object; but the object had no `step_plan` key, so `_parse_step_plan` rejected it. |
| Root Cause | The runtime's `PM_SYSTEM_PROMPT` constant bundled BOTH the role description AND the strict output-schema contract `{"step_plan":[…]}` into a single string. The PM call site resolved its system prompt with `cfg.system_prompt or PM_SYSTEM_PROMPT` — meaning **whenever a tenant had a custom prompt in the `llm_configs` row, the whole bundled default (including the schema) was replaced wholesale**, not extended. Klear's seeded `pm_tier_15` `system_prompt` is the IWO2-ported "Project Manager Alpha" prompt (5650 chars) that describes per-step evaluation criteria but never asks the LLM to emit a `step_plan` array. FFAI inherited the same Klear-style prompt via the BUG-062 baseline clone, so both tenants hit the same parser rejection. |
| Fix | Split `PM_SYSTEM_PROMPT` into two constants: `PM_BASE_ROLE_PROMPT` (role description, customizable per tenant) and `PM_OUTPUT_SCHEMA` (strict JSON contract, runtime-enforced). The call site now resolves `base_role_prompt = cfg.system_prompt or PM_BASE_ROLE_PROMPT` then unconditionally concatenates `+ PM_OUTPUT_SCHEMA`. Tenants may customize voice / role guidance via `llm_configs.system_prompt`, but the binding schema is always appended at the end. `PM_SYSTEM_PROMPT` is preserved as the composition `PM_BASE_ROLE_PROMPT + PM_OUTPUT_SCHEMA` for any external readers. This mirrors the established Tier-2 pattern (`DEFAULT_SYSTEM_PROMPTS[role] + TIER_2_OUTPUT_SCHEMA_BASE`) — Tier-2 was never vulnerable to this class of bug for the same reason. |
| Verified | 3 new regression tests in `test_tier_1_5_pm_groq_json_guard.py` (5 total): (a) the two new constants exist, the schema mentions the parsed keys, and `PM_SYSTEM_PROMPT == PM_BASE_ROLE_PROMPT + PM_OUTPUT_SCHEMA`; (b) the runtime source contains the literal `base_role_prompt + PM_OUTPUT_SCHEMA` concatenation (lock against future refactors that revert to the bundled-default pattern); (c) the existing BUG-061 lead-in test continues to pass. All 5 tests green. Live: FastAPI restarted; FFAI WO retry post-fix advances past the PM elaboration step. |
| Files Changed | `apps/api-fastapi/runtime/tier_1_5_pm.py` (~30 lines: split constant + retain composition + new call-site assignment with rationale comment), `apps/api-fastapi/tests/test_tier_1_5_pm_groq_json_guard.py` (~40 lines: 2 new regression tests + updated BUG-001→BUG-061 reference comment) |
| Related | Closes the second "Related residual" called out in BUG-062's entry — operators no longer need to remember to embed the schema when authoring custom PM prompts. Klear's existing `system_prompt` in the DB is unchanged (still 5650 chars of evaluation guidance); the schema is now appended at runtime by the call-site, not stored redundantly. The deeper config-resolver question — whether `TENANT_DEFAULT_ROLE=aiden_tier_1` fallback for missing PM/Tier-2 rows should swap in the module-level default prompt — remains open and is still captured for triage in BUG-062's Related block. |

### BUG-066: Aiden returns IWO2-era JSON shape when persona prompt embeds an obsolete OUTPUT FORMAT — `title missing or non-string` (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | High (intermittently blocks every chat turn on any tenant whose `aiden_tier_1` system_prompt was IWO2-ported — both Klear and FFAI hit this) |
| Status | Fixed, verified |
| Files | `apps/api-fastapi/runtime/tier_1_aiden.py`, `apps/api-fastapi/tests/test_tier_1_aiden_schema_supersedes.py` |
| Symptom | Operator on FFAI sent "Please process the PPT" after the BUG-065 fix. Aiden produced a visible chat brief ("Title: Create FFAI PPT Introduction (5 slides)…") but WO creation failed with `decision_malformed: decision_malformed: title missing or non-string`. The chat-side render parsed successfully (graceful fallback) but the dispatch-side validator rejected the same response. |
| Root Cause | Klear's seeded `aiden_tier_1` `system_prompt` is the IWO2-port (5765 chars) and contains a `═══ OUTPUT FORMAT — ALL DECISIONS AS JSON ═══` block at the bottom showing an IWO2-era shape: `{"phase": "...", "decision": "...", "mode": "...", "reasoning": "...", "assigned_agent": "...", "gcc": {...}, ...}`. No top-level `title` field. The IWO3 runtime correctly appends `AIDEN_OUTPUT_SCHEMA` (which DOES require top-level `title`) after the persona prompt — but the LLM saw TWO competing OUTPUT FORMAT blocks and intermittently produced the IWO2 shape, which `_parse_aiden_decision:411` rejects. Aiden's appended schema already had a `SUPERSEDES any earlier routing rules` clause for the role taxonomy (great), but no equivalent SUPERSEDES clause for the JSON schema itself. FFAI inherited the same Klear persona through the BUG-062 baseline clone. |
| Fix | Strengthened `_AIDEN_OUTPUT_SCHEMA_TEMPLATE` with an explicit "SUPERSEDES" clause for the JSON schema, mirroring the existing routing-taxonomy SUPERSEDES pattern. The new clause: (a) declares the schema below is THE contract, (b) explicitly names the obsolete IWO2 fields (`phase`, `decision`, `mode`, `reasoning`, `assigned_agent`) so the LLM can match against its own persona prose, (c) names the failure mode (`decision_malformed`) so the LLM understands what happens if it picks the wrong shape, (d) emphasises that `decision_kind` AND `title` are both required at the top level on every response (including `assistant_reply`). This is a prompt-engineering fix — no code-path change. |
| Verified | New regression suite `test_tier_1_aiden_schema_supersedes.py` — 3 tests: (a) the SUPERSEDES clause is present in `_AIDEN_OUTPUT_SCHEMA_TEMPLATE` and names the IWO2 `phase` field by token; (b) `decision_kind` + `title` still listed as required top-level fields; (c) the runtime source still concatenates `+ AIDEN_OUTPUT_SCHEMA` (lock against a future refactor that drops the append). All 3 pass; full BUG-061..065 + BUG-066 regression sweep 8/8 green. Live: FastAPI restarted; retry of the FFAI "Please process the PPT" intake produces a parseable Aiden response with top-level `title`. |
| Files Changed | `apps/api-fastapi/runtime/tier_1_aiden.py` (~15 lines: SUPERSEDES clause + "ALWAYS present" emphasis on `title`), `apps/api-fastapi/tests/test_tier_1_aiden_schema_supersedes.py` (~60 lines: new regression suite, 3 tests) |
| Related | Same class of bug as BUG-065 (PM schema) — both root-caused to IWO2-era prompt content being preserved verbatim in seed data and shadowing the IWO3 runtime contract. Long-term fix is a content audit of the Klear-seeded persona prompts to strip obsolete IWO2 schema/OUTPUT FORMAT blocks, since prompt-engineering belts have diminishing returns as IWO3's contract evolves further from IWO2's. Captured for triage. Note: the deeper config-resolver question from BUG-062's Related block (whether `TENANT_DEFAULT_ROLE=aiden_tier_1` should substitute the module-level default for missing roles) is unchanged; this fix only addresses Aiden's own customized prompt path. |

### BUG-067: Multi-step `workflow_brief` chains never advance past PM — no auto-advance worker, no UI button (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | High (every multi-step workflow dispatch on every tenant creates the chain then sits indefinitely; the entire CAP-A..CAP-G branded-chain runtime was effectively unreachable from the live UI) |
| Status | Fixed, verified |
| Files | `apps/api-fastapi/workers/workflow_step_worker.py` (new), `apps/api-fastapi/main.py`, `apps/api-fastapi/tests/conftest.py`, `apps/api-fastapi/routes/dispatch.py`, `apps/console-streamlit/api_client.py`, `apps/console-streamlit/views/work_orders.py` |
| Symptom | After BUG-066 cleared, FFAI "Create FFAI PPT Introduction (5 slides)" WO advanced through Aiden + PM cleanly (`work_order.transitioned: dispatch:workflow_brief` + `workflow_execution.started`) but then sat in `processing` status indefinitely. DB inspection showed `workflow_execution.status='running'` with all 4 `workflow_step_runs` (`content_brief` → `render` → `brand_qa` → `deliver`) stuck `pending`. No audit events after PM elaboration. |
| Root Cause | The dispatch chain has two paths: (1) `work_order_brief` (single-step) → calls `invoke_tier_2` synchronously inline; runs end-to-end in one HTTP turn. (2) `workflow_brief` (multi-step) → PM elaborates, `instantiate_workflow_from_brief` creates the `workflow_execution` + `workflow_step_runs` (all `pending`), then the dispatch handler RETURNS. The route `POST /workflows/{execution_id}/run_next_step` exists as the per-step advance contract, but **nothing was actually calling it** in the live system: the Streamlit work_orders UI exposed zero buttons that triggered it (grep `run_next_step` in `apps/console-streamlit/views/` → 0 callers), and no background worker scanned for pending step_runs. The CAP-A..CAP-G branded chains were unit-tested by pytest calling `run_next_step` directly, which hid the gap. |
| Fix | Two coordinated additions: (1) **Background worker** `apps/api-fastapi/workers/workflow_step_worker.py` (new, ~280 lines). Mirrors `wo_dispatch_worker` exactly: 10s tick (floor 5s), bypass-path scan for `workflow_executions WHERE status='running' AND EXISTS (pending step)`, per-execution tenant-scoped transaction, resolves `agent_system` actor + memory bundle, calls `execute_step_run` on the next pending step (one per execution per tick — keeps fairness across in-flight chains), emits `workflow_step.auto_advanced` or `workflow_step.auto_advance_failed` audit. Wired into `main.py` lifespan alongside the existing three workers. Disabled via `IWO3_WORKFLOW_STEP_WORKER_DISABLED` env var (mirrors the other workers' shape); `tests/conftest.py` defaults it to true so pytest TestClient lifespans don't auto-advance steps other tests are exercising. (2) **UI button** `views/work_orders.py` — new "Run next step" button in the Dispatch column, helper `api_client.run_next_workflow_step_by_wo(wo_id)`. Operator can force advancement / inspect between steps without waiting for the next worker tick. (3) **Convenience route** `POST /work_orders/{wo_id}/run_next_workflow_step` (in `routes/dispatch.py`) — looks up the WO's most recent `running` workflow_execution server-side and delegates to the existing `run_next_step` handler. The Streamlit client only knows the WO id, not the execution id; this saves a separate lookup. Returns `404 no_running_workflow_execution` with a hint when the WO is a single-step `work_order_brief` dispatch (so operators understand why the button doesn't apply). |
| Verified | Live: restarted FastAPI → `workflow_step_worker: starting (tick=10s)` logged → first tick discovered 4 executions with pending steps across both tenants → after several ticks the FFAI WO `51e2cfa9-3bb2-407d-b1d1-44b5e6d152db` advanced through all 4 steps end-to-end: `content_brief: completed` (Mark wrote a 5-slide brief), `render: completed` (Tom rendered a 7-slide branded PPTX), `brand_qa: failed` (Darla schema issue — separate bug), `deliver: skipped` (CAP-G revision-cycle rule). Worker correctly stopped touching the execution once no `pending` steps remained. Streamlit view-import smoke: 25/25 pass. The branded-chain runtime that CAP-A..CAP-G shipped is now actually reachable from the live UI flow. |
| Files Changed | `apps/api-fastapi/workers/workflow_step_worker.py` (new, ~280 lines: worker loop + advance helper + tenant scope helpers + actor cache, mirrors wo_dispatch_worker pattern), `apps/api-fastapi/main.py` (~12 lines: import + lifespan wiring), `apps/api-fastapi/tests/conftest.py` (~4 lines: disable flag default for pytest), `apps/api-fastapi/routes/dispatch.py` (~55 lines: convenience POST route + tenant-scoped lookup), `apps/console-streamlit/api_client.py` (~10 lines: helper), `apps/console-streamlit/views/work_orders.py` (~50 lines: Run next step button + status rendering) |
| Related | The Darla `brand_qa` schema failure surfaced by the worker's first end-to-end run is a separate same-class bug as BUG-065/066 (IWO2-era persona output shape doesn't match IWO3's parser). Not fixed here — captured for the next bug filing (likely BUG-068). The CAP-G revision-cycle rule (Darla `needs_revision` within cap → reset render+brand_qa; `block` or cap-reached → deliver skipped) is working as designed; the chain failed gracefully rather than infinite-looping. Long-term: workflow execution should auto-transition to `failed` when all steps have terminal status; right now the execution stays `running` after the worker stops touching it. That's a downstream tidiness fix, not blocking BUG-067 closure. |

### BUG-068: UNIVERSAL — structured-output mode contracts not enforced when tenant persona prompt is silent about them (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | High (every Tier-2 invocation in a structured mode — Darla brand_attestation, Paul intelligent_delivery, future modes — fails closed on any tenant whose persona prompt doesn't describe the runtime-required metadata fields. Klear-seeded personas are IWO2 ports and don't describe IWO3-era mode contracts; FFAI inherited the same via BUG-062 clone. Effectively blocks every branded chain at the `brand_qa` step on every tenant.) |
| Status | Fixed, verified |
| Files | `apps/api-fastapi/runtime/tier_2_subagents.py`, `apps/api-fastapi/runtime/tier_1_5_pm.py`, `apps/api-fastapi/runtime/darla_qa.py`, `apps/api-fastapi/runtime/paul_delivery.py`, `apps/api-fastapi/tests/test_bug_068_universal_mode_contract.py` (new) |
| Symptom | After BUG-067's workflow_step_worker landed, every branded-chain WO completed `content_brief` + `render` cleanly but consistently failed at `brand_qa`: `darla.qa_blocked` with notes `["Darla output did not match the structured contract; failing closed."]`. `deliver` then skipped (CAP-G revision-cycle rule). The same Klear/FFAI persona-prompt pattern that bit Aiden (BUG-066) and PM (BUG-065) bit Darla too, plus the same class would affect Paul's intelligent_delivery path once a chain made it that far. |
| Root Cause | **Class of bug, three sites.** Structured-output contracts (the exact metadata.* shape the runtime parser expects) were bundled inside `DEFAULT_SYSTEM_PROMPTS[role]` and lost wholesale when a tenant overrode `cfg.system_prompt`. Klear's seeded `darla_tier_2.system_prompt` is a 4290-char IWO2 port that describes design-critique guidance but doesn't mention `metadata.overall` / `palette_pass` / `fonts_pass` / `voice_pass` / `asset_pass`. SQL audit: `system_prompt ILIKE '%brand_attestation%'` returns `false` on both Klear and FFAI rows. So the LLM emitted a generic `content_envelope` with no metadata fields, `_parse_attestation` fell through to the fail-closed branch (block + "Darla output did not match the structured contract"), CAP-G revision-cycle saw a structural failure not content-disagreement and escalated to block, deliver skipped. Same pattern applies to Paul's `delivery_mode='intelligent'` path (metadata.outcome / adapter_key / template_profile_id) — not yet observed in production because no chain has made it through Darla, but waiting to fail the same way. |
| Fix | **Universal architectural fix, not a point patch.** The principle: structured-output contracts are runtime-enforced; persona prompts are voice/role guidance only. (1) **New runtime constants** in `tier_2_subagents.py` for each structured mode: `TIER_2_MODE_CONTRACT_BRAND_ATTESTATION` (Darla brand_qa: 5 required metadata fields + 3 allowed verdicts + semantics + parse-failure consequence) and `TIER_2_MODE_CONTRACT_INTELLIGENT_DELIVERY` (Paul branded-deliver: 6 required metadata fields + 3 allowed outcomes + decision rules + parse-failure consequence). Each contract explicitly says "Override any persona-level handoff prose" so the LLM resolves the conflict in favor of the runtime contract. (2) **New parameter `mode_contract: str = ""`** plumbed through `invoke_tier_2` → `_invoke_tier_2_once` → `composed_schema = schema + (mode_contract or "")`. Empty default preserves all existing callers. (3) **Caller wiring**: `darla_qa.invoke_darla_qa` now always passes `mode_contract=TIER_2_MODE_CONTRACT_BRAND_ATTESTATION`; `paul_delivery.invoke_paul_delivery` always passes `mode_contract=TIER_2_MODE_CONTRACT_INTELLIGENT_DELIVERY`. (4) **SUPERSEDES clauses** added to `TIER_2_OUTPUT_SCHEMA_BASE`, `TIER_2_OUTPUT_SCHEMA_NO_TOOL_CALL`, AND `PM_OUTPUT_SCHEMA` — names obsolete IWO2 fields by token (`phase`, `decision`, `score`, `verdict`, `next_action`, `assessment`, etc.) so the LLM can match against its own persona prose. Mirrors the BUG-066 Aiden pattern, now applied universally across Tier-1 (Aiden), Tier-1.5 (PM), and Tier-2 (sub-agents). |
| Verified | New regression suite `test_bug_068_universal_mode_contract.py` — 9 tests covering: (1-2) both Tier-2 base schemas have SUPERSEDES; (3) PM_OUTPUT_SCHEMA has SUPERSEDES; (4) brand_attestation contract names all 5 required fields + 3 verdicts; (5) intelligent_delivery contract names all 6 required fields + 3 outcomes; (6) runtime accepts `mode_contract` param + composes it after the base schema; (7-8) Darla + Paul always pass their respective contracts; (9) BUG-066 Aiden SUPERSEDES lock still holds. **Full BUG-061..066 + BUG-068 sweep: 17/17 green.** Live verification: created fresh FFAI workflow_execution `1c8c46f5-…` post-fix; worker advanced content_brief + render to completed; **Darla now produces real structured output** — audit row shows `darla.qa_blocked` with `metadata.verdict='block'`, `palette_pass=true`, and a substantive brand-review note (`"The brand mentioned in the content ('FreedomForge') does not match the default brand..."`). Before fix: Darla audit had parser-fallback notes (`"Darla output did not match the structured contract; failing closed."`). After fix: Darla audit has Darla's own review prose, populated per-criterion flags, and a real verdict. The block this time is a legitimate content concern (FFAI content rendered against Klear default templates — BUG-003 stand-in posture), not a structural failure. Paul's path not exercised live (deliver step skipped after brand_qa block) but the runtime contract is identical and the regression tests lock the wiring. |
| Files Changed | `apps/api-fastapi/runtime/tier_2_subagents.py` (~120 lines: SUPERSEDES clauses on both schemas + 2 new mode-contract constants + mode_contract param threaded through `invoke_tier_2` + `_invoke_tier_2_once` + rationale comments), `apps/api-fastapi/runtime/tier_1_5_pm.py` (~10 lines: SUPERSEDES clause added to PM_OUTPUT_SCHEMA), `apps/api-fastapi/runtime/darla_qa.py` (~10 lines: import + pass mode_contract), `apps/api-fastapi/runtime/paul_delivery.py` (~10 lines: same), `apps/api-fastapi/tests/test_bug_068_universal_mode_contract.py` (~155 lines: 9-test regression suite) |
| Related | This is the **universal closure** of the BUG-065/066/068 cluster. The principle — **runtime contracts win over persona prompts; personas are voice/role guidance only** — now holds at every tier (Aiden, PM, all Tier-2 modes). Future structured modes (e.g. SOP Master template generation, Nyx compliance review) can add a `TIER_2_MODE_CONTRACT_*` constant and pass `mode_contract=...` at the call site to inherit the same enforcement. Long-term content audit of Klear's IWO2-ported personas remains a separate cleanup task (would let the prompts shed redundant schema language now that the runtime enforces it), but the cluster is closed: the system no longer depends on operator-tunable text to enforce a runtime contract. The remaining FFAI-specific block (Darla legitimately flagging the brand mismatch) is a content concern that BUG-003's FFAI-template cutover will resolve, not a runtime bug. |

### BUG-069: FFAI tenant data hygiene cluster — Klear-cloned persona pollution + empty brand_profile + stale Paul model + Gamma credential_ref env-var mismatch (High)

| Field | Detail |
| --- | --- |
| Date | 2026-05-16 |
| Severity | High (chain ran end-to-end at the code level after BUG-068, but every FFAI branded WO consistently blocked at brand_qa or deliver due to four overlapping data-hygiene issues on the FFAI tenant rows. Operator-visible effect: FFAI WOs never reached a live Gamma render despite all runtime fixes being in place.) |
| Status | Fixed, verified end-to-end |
| Files | live DB only (FFAI rows in `client_brand_profiles`, `llm_configs`, `adapter_credentials`); `db/seeds/client_brand_profiles.json`, `db/seeds/llm_configs.json`; `apps/api-fastapi/runtime/tier_2_subagents.py` (intelligent_delivery contract polish) |
| Symptom | After BUG-068 closed the runtime-contract cluster, FFAI multi-step PPTX WO `51e2cfa9-3bb2-407d-b1d1-44b5e6d152db` advanced through Aiden + PM + Mark + Tom but Darla then `block`ed with: *"The brand mentioned in the content ('FreedomForge') does not match the default brand ('Klear.ai') or the provided canonical facts ('FFAI'). Please correct the brand name throughout the document."* Subsequent runs surfaced two more downstream failures: `paul_decision: response_invalid: groq returned HTTP 404: The model 'moonshotai/kimi-k2-instruct' does not exist or you do not have access to it`, then `output_malformed: content_markdown missing or empty`, then `credential_missing: env var GAMMA_REGISTRY_TEST_KEY is not set or empty`. Each fix unblocked the next layer until the chain reached a live Gamma generation ID. |
| Root Cause | **Four overlapping data-hygiene issues on FFAI tenant rows, all introduced by the BUG-062 baseline clone (which copied Klear's seed verbatim) or by stale upstream seed data.** (1) **Persona pollution** — `llm_configs.system_prompt` for FFAI's 10 non-Aiden roles was a verbatim copy of Klear's IWO2-ported persona prompts. Klear's Darla prompt is 4290 chars and *hard-mentions "Klear.ai"* throughout (e.g. *"default: Klear.ai palette"*). When Darla scored FFAI content, she literally read "default brand: Klear.ai" in her own system prompt and flagged the brand mismatch. The same Klear-language pollution applied to all 10 cloned roles. (2) **Empty FFAI brand_profile** — CAP-A seeded a skeleton `client_brand_profiles` row for FFAI with `brand_terms` populated but `palette_json={}`, `fonts_json={}`, `voice_brief=NULL`, `icp_summary=NULL`, `requires_brand_qa=FALSE`. Darla had nothing FFAI-specific to score against, so when her persona's Klear-default reference fired she had no FFAI counter-evidence. (3) **Stale Paul model** — Paul's `llm_configs.model='moonshotai/kimi-k2-instruct'` was decommissioned by Groq; the API returned HTTP 404 `model_not_found`. Same stale row inherited from Klear on both tenants. (4) **Gamma credential_ref mismatch** — `adapter_credentials.credential_ref='credential_ref:env:GAMMA_REGISTRY_TEST_KEY'` but the actual env var name in `.env` is `GAMMA_API_KEY`. The runtime resolver looked up the wrong env var name and got nothing. Same stale row inherited from the original seed on both tenants. |
| Fix | **Coordinated four-part repair, all on tenant data + one runtime-contract polish.** (1) **Populate FFAI `client_brand_profiles`** with real brand attributes extracted from `WS009_FFAI (TCM)/05_AIden Knowledge Base/`: `voice_brief` (634 chars synthesized from FFAI Sales Pitch + Future Build Concept — practical/warm/no-BS/action-oriented voice), `icp_summary` (994 chars — five-persona summary from WHY USE FFAI Website), `palette_json` (blue + navy inferred from the Napkin-rendered directive diagrams: `#2563EB` primary, `#1E40AF` accent, `#1E3A8A` gradient end), `fonts_json` (Inter heading + body, JetBrains Mono), `brand_terms` (extended from 7 → 24 entries adding TIB, TRACE, Aiden Zephyr, Jamie Forge, and the named tooling), `requires_brand_qa=TRUE`, `design_input_sources_json` recording the WS009 provenance + note that palette/fonts are inferred pending an official FFAI brand book. (2) **Null out FFAI's 10 cloned `llm_configs.system_prompt`** rows so the resolver falls back to the tenant-neutral runtime `DEFAULT_SYSTEM_PROMPTS[role]` — these are the canonical IWO3 personas (no Klear hardcoding, correct brand_attestation Mode 2 contract description). Klear keeps its own persona overrides since they're intentional Klear customization. (3) **Bump Paul's model** on both tenants from `moonshotai/kimi-k2-instruct` to `openai/gpt-oss-120b` (currently available on Groq, used by other roles already). (4) **Repair Gamma `credential_ref`** on both tenants from `credential_ref:env:GAMMA_REGISTRY_TEST_KEY` to `credential_ref:env:GAMMA_API_KEY` (matches the actual `.env` variable name). (5) **Polish `TIER_2_MODE_CONTRACT_INTELLIGENT_DELIVERY`** to explicitly remind the LLM that `content_envelope.content_markdown` is still required by the base envelope schema, with an example 1-2 sentence delivery summary template — surfaced when Paul's first post-fix attempt emitted only `metadata` and tripped `output_malformed: content_markdown missing or empty`. (6) **Persist all data changes in seed JSONs** (`db/seeds/client_brand_profiles.json`, `db/seeds/llm_configs.json`) so future reseeds don't reintroduce the pollution. |
| Verified | Live end-to-end run on `51e2cfa9-3bb2-407d-b1d1-44b5e6d152db` after all five fixes: workflow_execution `6ff3eb73-8a67-41cd-9fde-9c4e58adc419` advanced through all 4 steps to completion. **content_brief**: completed (Mark). **render**: completed (Tom, output noted *"with brand-compliant styling"* — picked up the FFAI palette + Inter fonts from the populated brand_profile). **brand_qa**: completed `verdict=pass` on attempt 1 with all four criteria green (`palette_pass=true, fonts_pass=true, voice_pass=true, asset_pass=true`). **deliver**: completed `outcome=primary_dispatch`, `adapter_key=gamma`, `template_profile_id=ffai_pptx_gamma_basic`, `decision_reason="Single registered template matches package; using primary adapter"`, **`handoff_id=e8efe1e8-7913-4056-afe8-315f7ed48caf`**, **`external_reference=YZJnav9ZMqfM4ofS4B0pL` (live Gamma generation ID)**. First live Gamma render to ship through the full FFAI branded chain. Prior execution (before BUG-069 fixes) had brand_qa attempt-1 `needs_revision` (palette_pass=false, fonts_pass=false) → render redo → attempt 2 pass — proves Darla's revision-cycle logic also works correctly now that she has a real brand profile to score against. |
| Files Changed | Live DB: FFAI `client_brand_profiles` row updated (revision 1 → 3), 10 FFAI `llm_configs` rows nulled `system_prompt`, 2 `llm_configs` Paul rows model bumped, 2 `adapter_credentials` rows credential_ref repaired. Seed: `db/seeds/client_brand_profiles.json` (+5 fields populated for FFAI), `db/seeds/llm_configs.json` (10 FFAI rows nulled + 2 Paul rows model bumped). Runtime: `apps/api-fastapi/runtime/tier_2_subagents.py` (~10 lines added to `TIER_2_MODE_CONTRACT_INTELLIGENT_DELIVERY` reminding Paul that `content_markdown` is still required). |
| Related | Brand palette + fonts in FFAI's `client_brand_profiles` are **inferred from the Napkin-rendered directive diagrams** in WS009; the FFAI team should supply an official brand book when ready and the inferred values can be replaced via a `client_brand_profiles.update` (revision bumps automatically). The Klear-side data-hygiene parallels — Klear also had the stale Paul model + the Gamma credential_ref mismatch — were repaired in the same pass. The tenant-clone-as-baseline pattern (BUG-062) is now retired as a default: future tenant onboarding should start with `system_prompt=NULL` (runtime defaults) + a populated `client_brand_profiles` row from operator-supplied brand input, not a Klear clone. Captured for the onboarding runbook update. |

---

## Session — IWO3 Workspace UX (2026-05-17)

Operator: Darrel Vaughn | Reviewer: Claude Opus 4.7 | Tree: IWO3 (`iwo3/main`)

### BUG-070: Workspace folder grid has no sort + no search — outputs pile up unorderable (Medium)

| Field | Detail |
| --- | --- |
| Date | 2026-05-17 |
| Severity | Medium (every operator viewing a folder with > ~10 items hits this; the Outputs folder fills with multi-attempt branded chain artifacts and there is no way to find the latest render) |
| Status | Fixed, verified |
| Files | `apps/console-streamlit/views/workspace.py` |
| Symptom | Operator on `localhost:8504/workspace` opened the Outputs folder (containing ~30 items — many near-duplicate names like "Mark — branded content brief (PPTX)") and reported: *"why is there no way to sort the Workspace content - it should be organized by date by default but also should be sortable and searchable"*. The grid was alphabetical-by-name only; no toolbar; no way to find the most recent render among many same-titled cards. |
| Root Cause | `views/workspace.py::_render_grid` sorted both folders and files alphabetically by name (lines 548-549 pre-fix). The caller at the bottom of `main()` also pre-sorted alphabetically. No search input, no sort dropdown, no toolbar surface at all. The API surface had everything needed already: `routes/workspace.py` `list_workspace_files` SELECT returns `created_at::text` + `updated_at::text` per row alongside `filename` + `mime_type`. Pure UI gap; backend data was there the whole time. |
| Fix | Added a per-folder toolbar above the grid in `views/workspace.py`. Two controls: (a) **search input** — `st.text_input` with `🔎 Filter N item(s) by name…` placeholder; case-insensitive substring filter against `folder.name` for folders and `file.filename` for files; renders a `Showing X of Y item(s) matching '…'` caption when active, or a friendly info banner when zero matches. (b) **sort dropdown** — `st.selectbox` with six options: `Newest first (created)` (default), `Oldest first (created)`, `Recently modified`, `Name A → Z`, `Name Z → A`, `Type`. Folders use the same vocabulary but fall back to alpha for "Type" (folders have no mime_type). Folders stay above files in the grid (file-explorer convention) but within each group the order respects the chosen sort. Two new helpers: `_sort_files(files, choice)` + `_sort_folders(folders, choice)` consume key-fn + reverse tuples from `_file_sort_key_factory` / `_folder_sort_key_factory`. Toolbar state is keyed per folder (`ws-search-{folder_id}` + `ws-sort-{folder_id}`) so moving between folders preserves per-folder search/sort context. Default sort changed from alphabetical to **Newest first (created)** because the Outputs folder fills up faster than operators can alphabetize. |
| Verified | Streamlit view-import smoke 25/25 still green. Live: `/workspace` returns 200; refresh shows the toolbar above the grid; typing into search filters live; sort dropdown switches order in place. No backend or schema change required — the existing `/workspace/tree` and `/workspace/folders/{id}` responses already include `created_at` + `updated_at` per row, the UI just wasn't using them. |
| Files Changed | `apps/console-streamlit/views/workspace.py` (~75 lines: 2 sort-key factories + 2 sort helpers + `_render_grid_toolbar` + caller refactor + tuple of SORT_CHOICES; pre-fix alphabetical pre-sort removed from both `_render_grid` body and the main() call site) |
| Related | **Scope notes (intentional residuals):** (1) Search is **folder-scoped only** — searches only the current folder, not the entire workspace tree. Global cross-folder search is an additive follow-on (would want a separate `?global=true` toggle or an "Include subfolders" checkbox). (2) **No mime-type filter chips** (e.g. "PPTX only / PDF only / HTML only" pills) — sort-by-Type already groups them together, but explicit chips would be a third toolbar row if operators want faceted filtering. Skipped for first pass. (3) Toolbar appears on **every folder including the root** — could conditionally hide when item count < 5 to reduce visual noise, but operators may still want search even for small folders. Leaving on by default. |

### BUG-071: Non-gamma output_package WOs never auto-complete — stuck in `processing` forever (High, hot-fix)

| Field | Detail |
| --- | --- |
| Date | 2026-05-17 |
| Severity | High (every WO whose Tier-2 produced a `generic` / `sandbox_*` / `*_html_render` / `email_campaign` etc. package — i.e. anything not `gamma_*` — sits in `processing` indefinitely after Tier-2 finishes. Aiden's chat-route "where is the deliverable?" query reports `status: processing` because that's what the row says, while the actual deliverable content is sitting in `output_packages.content_blocks` ready to read. Hot-fixed and shipped within the same session.) |
| Status | Fixed, verified, hot-fix applied to hosted backfill row |
| Files | `apps/api-fastapi/workers/wo_dispatch_worker.py` |
| Symptom | Operator created a "SOP for FF.AI Partner Onboarding" WO via the hosted Streamlit chat (`f8cb248f-cf50-4b36-ab7b-7cd63f27001e`, FFAI tenant). Tier-1 → Tier-2 (`sop_master_tier_2`) completed in ~10 seconds; produced output_package `5a985539...` with a full 10-section SOP markdown in `content_blocks`. Operator then asked "where is the deliverable?" 50 minutes later. Aiden's reply: *"Your SOP for FF.AI Partner Onboarding is currently processing… status: processing… The deliverable will be available once the work order completes."* — technically true (the WO row was still `processing`), but operator-misleading because the deliverable was already there. |
| Root Cause | `apps/api-fastapi/workers/wo_dispatch_worker.py::dispatch_one_wo` has a completion branch for `gamma_*` output_kinds (line ~406: `if envelope.output_kind.startswith("gamma_"): dispatch_gamma_for_package(...)` and the `poll_worker` advances the WO when the Gamma handoff lands). For every other `output_kind` (the `output_package_kind` enum has 17 values; only 2 are `gamma_*`), there is NO completion trigger in the worker. The WO transitions `pending → processing` correctly at line 318-326, the package is created, the audit row fires `work_order.auto_dispatch_succeeded`, then the function returns `"work_order_brief"` with the WO STILL in `processing`. Nothing downstream moves it. The deliverable content lives in `output_packages.content_blocks` but operators viewing the WO row see `processing` forever. |
| Fix | Insertion at `wo_dispatch_worker.py:443` (immediately before `return "work_order_brief"` and after the existing `auto_dispatch_succeeded` audit): when `envelope.output_kind` does NOT start with `gamma_`, call `transition_work_order(..., to="completed", reason=f"auto_complete:package_kind={envelope.output_kind}")` wrapped in `try/except IllegalTransition` (operator may have moved it concurrently). gamma_* path unchanged — poll_worker still owns gamma WO completion via the handoff lifecycle. ~16 lines added. The transition itself writes its own `work_order.transitioned` audit row via the standard `transition_work_order` helper, so the audit trail records both `auto_dispatch_succeeded` (package created) and `work_order.transitioned` (WO moved to completed) for forensic clarity. |
| Verified | Five regression tests in `apps/api-fastapi/tests/test_wo_dispatch_worker_tool_call.py`, all green: `test_tool_call_followup_work_order_brief_proceeds_to_package` (now also asserts WO ends `completed` post-fix), `test_gamma_kind_does_not_auto_complete_wo` (NEW — asserts gamma_* leaves WO in `processing` so poll_worker still owns completion), `test_tool_call_followup_workflow_brief_proceeds_to_pm`, `test_repeated_tool_call_hits_decision_kind_unknown_cap`, `test_tool_call_tool_failure_audits_explicitly`. Full pytest: 646 passed, 1 skipped (was 645; +1 new). `npm run check` clean. **Hosted backfill:** the stuck FFAI WO `f8cb248f-cf50-4b36-ab7b-7cd63f27001e` was manually transitioned `processing → completed` via a direct UPDATE + audit row on the hosted DB, with `reason="manual_complete:bug_071_hotfix_backfill"` so the audit row is forensically distinguishable from future worker-driven auto-completions. |
| Files Changed | `apps/api-fastapi/workers/wo_dispatch_worker.py` (~16 lines added; existing handlers untouched), `apps/api-fastapi/tests/test_wo_dispatch_worker_tool_call.py` (+1 new test for gamma_* skip + 1 assertion extension on existing test) |
| Related | **Scope:** narrowest fix that closes the operator-visible gap. Does NOT change behavior for `gamma_*` (poll_worker still drives those), `workflow_brief` (multi-step path; workflow_executions auto-terminate is the separate concern in Loop Omicron scope), or adapter-handoff kinds (email_campaign, drive_upload, crm_mutation, figma_handoff, stitch_handoff, designlab_handoff — these get auto-completed too because the worker doesn't fire their adapter handoffs itself; if those kinds need a separate "wait for adapter completion" gate, surface as a separate BUG). **Adjacent gap NOT fixed here:** Aiden's chat-route "where is the deliverable?" handler still checks `work_orders.status` only and doesn't query `output_packages.work_order_id` to discover packages on a still-processing WO. With BUG-071 fixed, this is no longer operator-visible for the common case, but the chat-route grounding could still mislead for a workflow_brief WO in progress. Captured for future Aiden chat grounding loop. **Loop Omicron** auto-terminate concern (workflow_executions don't transition when step_runs all reach terminal) is conceptually adjacent but at the workflow level; BUG-071 only addresses single-step WO auto-completion. |

### BUG-072: Workspace renderer dumps raw JSON for every Tier-2 output_package — operators see garbage instead of the rendered deliverable (High, hot-fix)

| Field | Detail |
| --- | --- |
| Date | 2026-05-17 |
| Severity | High (every Tier-2 output_package the operator opens in the Workspace surface — SOPs, briefs, decks, anything where a sub-agent shipped the deliverable as `content_markdown` — renders as a wrapper saying "Output Package — generic" + the literal phrase "## Raw content_blocks" + the JSON blob, instead of the actual rendered content the sub-agent produced. Affects every existing tenant + every existing output_package. Surfaced after BUG-071 closed the auto-complete gap, exposing this as the next operator-visible layer.) |
| Status | Fixed, verified |
| Files | `apps/api-fastapi/routes/workspace.py` (single helper edit; ~18 lines net) |
| Symptom | Operator opened the FFAI SOP output_package in the Workspace UI right after BUG-071 hot-fix completed the WO. Saw: `# Create SOP for FF.AI Partner Onboarding` / `_Output Package — generic_` / "Provided FF.AI Partner Onboarding SOP document." / `## Raw content_blocks` / a fenced JSON dump containing the actual SOP markdown buried inside a `"prompt": "..."` string with `\n` escapes. Real SOP content was in `content_blocks.content_markdown` (1480 bytes of well-formatted markdown — 10 sections from Introduction through Review & Feedback) and `content_blocks.prompt` (identical 1480-byte duplicate), but the Workspace renderer didn't recognize either key. |
| Root Cause | `apps/api-fastapi/routes/workspace.py::_serialize_output_package_to_markdown` (lines 1098-1161 pre-fix) only knew about ONE canonical shape: `{"sections": [{"title", "body"}, ...]}`. Tier-2 sub-agent envelopes (`sop_master_tier_2`, `mark_tier_2`, etc.) ship `content_blocks` with a DIFFERENT shape: `{prompt, summary, metadata, content_markdown}` where `content_markdown` is the rendered deliverable. Since `blocks.get("sections")` returned None for every Tier-2 envelope, the function fell through to the "Unknown shape" branch (lines 1147-1156) and dumped the raw JSON in a code fence. This was the last-resort safety net — but it had been silently misfiring for EVERY Tier-2 output_package since the helper landed during Sandbox Everywhere Darkmode follow-on (2026-05-12), because no Tier-2 envelope has ever conformed to the `sections` shape. |
| Fix | Extended the renderer's fallback chain in the "no sections" branch. New probe order: (1) `content_blocks.sections[]` (canonical, existing behavior unchanged), (2) `content_blocks.content_markdown` (Tier-2 envelope canonical body key), (3) `content_blocks.markdown` (defensive — other naming), (4) `content_blocks.prompt` (legacy Tier-2 envelope body key — sop_master_tier_2 ships this as a duplicate of content_markdown). When any of (2)/(3)/(4) is a non-empty string, the renderer surfaces it directly as the body. Only when NONE match does the raw-JSON dump fire — preserved as the last-resort safety net for genuinely unknown shapes so operators never see a blank preview. The `# {title}` / `_Output Package — {output_kind}_` / `{summary}` preamble + the empty-content_blocks fallback are unchanged. |
| Verified | 4 new focused unit tests in `apps/api-fastapi/tests/test_workspace_route.py`: (1) `test_serialize_output_package_recognizes_content_markdown_key` — exact repro of the SOP shape, asserts real markdown surfaces + raw-JSON dump does NOT fire. (2) `test_serialize_output_package_prefers_sections_over_content_markdown` — pins precedence so canonical-shape envelopes still win. (3) `test_serialize_output_package_recognizes_prompt_key_as_fallback` — pins the prompt-only path defensively. (4) `test_serialize_output_package_falls_back_to_raw_for_truly_unknown_shape` — last-resort behavior preserved. All 4 green. Full pytest: 650 passed, 1 skipped (was 646; +4 new). The existing `test_file_content_fetch_renders_output_package_to_markdown` (the canonical sections-shape happy path) still passes — no regression on canonical envelopes. |
| Files Changed | `apps/api-fastapi/routes/workspace.py` (~18 lines net: probe loop + body_md assignment + nested if/else for raw-JSON fallback; existing canonical sections path + preamble + empty-content_blocks fallback untouched), `apps/api-fastapi/tests/test_workspace_route.py` (+4 unit tests appended) |
| Related | **Scope:** narrowest fix in the renderer that closes the operator-visible gap. Does NOT change Tier-2 envelope shape (sop_master_tier_2 and friends keep shipping `{prompt, summary, metadata, content_markdown}` — making them conform to `{sections: [...]}` would be a much bigger architectural slice with risk of breaking other consumers). Does NOT change the output_packages.content_blocks DB schema. Does NOT change the package-creation path. **Adjacent question NOT addressed:** *should* all sub-agent envelopes converge on one canonical content_blocks shape long-term? Probably yes — having two parallel shapes is fragile (every renderer needs to know about both). But that's an architectural cleanup, not an operator-visible bug. Captured for future loop. **Operator backfill:** existing output_packages on hosted are unchanged — the renderer fix is read-time, so refreshing the Workspace UI immediately shows the real markdown for every existing package (no data migration needed). The two stuck FFAI SOP packages (85e4755e + 5a985539 from BUG-071 backfill) will render correctly once Railway redeploys this commit. **Successor of BUG-071** — closing BUG-071's auto-completion gap exposed BUG-072 (which had been silently misfiring for every Tier-2 package since 2026-05-12 but was invisible because every WO was stuck in `processing` and operators rarely opened the package in the Workspace). Same operator session; same hot-fix discipline. |

---

## Summary

Per-session bug counts are the count of unique `BUG-###` IDs first
introduced in that session. Follow-up patches that re-use a prior ID
(e.g. `BUG-050 Extension`, `BUG-053 Hardened`, the second mention of
`BUG-054` in Session 14) are documented in their session block but
NOT double-counted in the totals below. Severity rollups are tallied
from each unique ID's first-occurrence title or `| Severity |` table
row.

| Category | Count | Critical | High | Medium | Low |
| --- | --- | --- | --- | --- | --- |
| Bugs fixed (Session 1, 2026-03-03) | 4 | 2 | 1 | 1 | 0 |
| Bugs fixed (Session 2, 2026-03-04/05) | 6 | 1 | 1 | 4 | 0 |
| Bugs fixed (Session 3, 2026-03-05) | 3 | 0 | 3 | 0 | 0 |
| Bugs fixed (Session 4, 2026-03-06/07) | 3 | 1 | 1 | 1 | 0 |
| Bugs fixed (Session 5, 2026-03-07) | 4 | 0 | 3 | 1 | 0 |
| Bugs fixed (Session 7, 2026-03-07) | 5 | 0 | 4 | 1 | 0 |
| Bugs fixed (Session 8 — IWO2 Hardened Init, 2026-03-08) | 1 | 1 | 0 | 0 | 0 |
| Bugs fixed (Session 9 — v0.9.2 / v0.9.5 Release, 2026-03-13/14) | 8 | 0 | 4 | 3 | 1 |
| Bugs fixed (Session 10 — v0.9.5 Hotfixes, 2026-03-14) | 3 | 1 | 2 | 0 | 0 |
| Bugs fixed (Session 11 — Gamma PPTX + Workflow Post-Processing, 2026-03-15) | 5 | 2 | 3 | 0 | 0 |
| Bugs fixed (Session 12 — Execution Reliability, 2026-03-21) | 6 | 0 | 4 | 2 | 0 |
| Bugs fixed (Session 12b — features + BUG-053 Hardened follow-up; no new IDs) | 0 | — | — | — | — |
| Bugs fixed (Session 13, 2026-03-27) | 1 | 0 | 1 | 0 | 0 |
| Bugs fixed (Session 14 — Know-How Chat Retrieval Hardening, 2026-03-27/28) | 3 | 1 | 2 | 0 | 0 |
| Bugs fixed (IWO3 Chat Correlation-ID Collision, 2026-05-03) | 1 | 0 | 1 | 0 | 0 |
| Bugs fixed (IWO3 Dashboard Recent-WO Click Auth Loss, 2026-05-10) | 1 | 0 | 1 | 0 | 0 |
| Bugs fixed (IWO3 Loop Xi Recovery Gate Too Narrow, 2026-05-10) | 1 | 0 | 0 | 1 | 0 |
| Bugs fixed (IWO3 FFAI Tenant Onboarding + Auth Polish, 2026-05-16) | 9 | 0 | 7 | 2 | 0 |
| Bugs fixed (IWO3 Workspace UX, 2026-05-17) | 1 | 0 | 0 | 1 | 0 |
| **Total bugs fixed (unique BUG-IDs)** | **65** | **9** | **38** | **17** | **1** |
| Feature implementations (Session 6, 2026-03-07) | 3 | — | — | — | — |
| Feature implementations (Session 12b, 2026-03-25) | 1 | — | — | — | — |
| Feature implementations (Session 14, 2026-03-27/28) | 3 | — | — | — | — |
| Code review findings | 6 | 0 | 0 | 1 | 5 |
| Performance findings | 1 | — | — | — | — |
| Infrastructure changes | 6 | — | — | — | — |

### Numbering convention notes

- Gaps in numbering are intentional (e.g. `BUG-043`..`BUG-047` were
  tracked locally during a loop that ultimately closed without
  shipping a separate fix). Do not reuse retired numbers; advance to
  the next free `BUG-###` (currently `BUG-071`) when filing a new
  entry.
- Follow-up patches on a prior bug should use a labeled re-entry
  (e.g. `### BUG-050 Extension: ...`, `### BUG-053 Hardened: ...`)
  under their own session so the audit trail is intact, but they
  count as zero new IDs in this Summary.
- The duplicate `BUG-054` heading (Session 13 line 994 + Session 14
  line 1016 "Loop 15: BUG-054 — Know-How Parser Fix") is the same
  bug documented across two writing sessions; first occurrence
  (Session 13) wins in the count.
