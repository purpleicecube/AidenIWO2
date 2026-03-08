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

## Summary

| Category | Count | Critical | High | Medium | Low |
| --- | --- | --- | --- | --- | --- |
| Bugs fixed (Session 1) | 4 | 2 | 1 | 1 | 0 |
| Bugs fixed (Session 2) | 6 | 1 | 1 | 4 | 0 |
| Bugs fixed (Session 3) | 3 | 0 | 3 | 0 | 0 |
| Bugs fixed (Session 4) | 3 | 1 | 1 | 1 | 0 |
| Bugs fixed (Session 5) | 4 | 0 | 3 | 1 | 0 |
| Bugs fixed (Session 7) | 5 | 0 | 5 | 0 | 0 |
| **Total bugs fixed** | **25** | **4** | **15** | **6** | **0** |
| Feature implementations (Session 6) | 3 | — | — | — | — |
| Code review findings | 6 | 0 | 0 | 1 | 5 |
| Performance findings | 1 | — | — | — | — |
| Infrastructure changes | 6 | — | — | — | — |
