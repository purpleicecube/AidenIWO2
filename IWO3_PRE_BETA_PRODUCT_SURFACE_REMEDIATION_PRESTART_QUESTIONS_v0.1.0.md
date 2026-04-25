# IWO3 Pre-Beta Product Surface Remediation — Prestart Questions v0.1.0

Date: 2026-04-25
Status: Locked (architect answers received 2026-04-25). Execution authorized in dangerous mode.
Predecessors: `IWO3_ALPHA_CLOSEOUT_GAP_PUSH_RECORD_v0.1.0.md`, `IWO3_PRE_BETA_GAP_CLOSURE_RECORD_v0.1.0.md`, `MEGALOOP_ALPHA_RECORD_v0.1.0.md`.
Successor: MegaLoop Beta (separate loop; cannot open until this loop closes).

This is the formal Stage 0 artifact for the Pre-Beta Product Surface Remediation Loop ("Loop δ"). It records the architect-locked answers to the five showstopper questions raised before execution and bakes in defaults for the remaining Stage 0 categories.

## Architect-locked answers (showstoppers, all five)

### 1. Workspace storage substrate — **B with discipline**

Use the existing `artifacts` table as the **file substrate** plus a new `workspace_folders` table for the folder tree. Filesystem is **not** the primary model for this loop.

**Rationale:** `artifacts` already carries tenant-scoped `iwo3_native/drizzle` ownership, RLS, and audit anchoring; reusing it ties workspace storage directly to the existing output_package → artifact path. A parallel "workspace files" table would force every CRUD path to keep two records in sync. Architect's note: **artifact integration is the center of gravity — Workspace is the operator's structured landing zone for outputs, drafts, and related working files, not just a file browser.**

Schema impact (target):
- New table: `workspace_folders` (`id`, `client_id`, `parent_folder_id NULL`, `name`, `created_at`, `updated_at`, `deleted_at NULL` for soft delete, `created_by_user_id`).
- Extend `artifacts`: add `workspace_folder_id NULL` (FK → `workspace_folders.id`) so an artifact can live inside a workspace folder.
- New unique on `workspace_folders` `(client_id, parent_folder_id, name)` so siblings don't collide; enforced inside RLS-scoped tx.
- RLS: forced on `workspace_folders` matching the existing `artifacts` policy shape.

### 2. Drag-and-drop authority — **A required**

Ship literal drag-and-drop, not a "Move to…" dropdown. Prefer a pinned, scoped Streamlit custom component dependency over building a React component from scratch.

**Implementation path:** evaluate `streamlit-sortables` first (single-list and grouped-list drag-drop, light dependency). If `streamlit-sortables` cannot satisfy nested-folder + file-into-folder semantics, fall back to a tree-select-style dependency. Custom React component only as last resort.

**Acceptance:** an operator can grab a file or folder card in the Workspace UI, drop it onto a different folder card, and the move persists. Cut+paste / explicit "Move to…" actions are kept as a keyboard-accessible secondary path.

### 3. Aiden persona source of truth — **C with precedence**

Hybrid:
- `IWO2 runtime code` (`/home/virgina/VS_AIDEN_IWO2/server/...`) is the operator-facing voice/tone source of truth.
- `aiden_alpha_spec` (`/home/virgina/aiden_alpha_spec`) is the contract/intent guardrail.
- **Conflict rule:** if the two diverge on conversational personality, IWO2 runtime wins for this loop. No split-brain Aiden.

The persona seeded today (`llm_configs.system_prompt` for `aiden_tier_1`) is a 274-char stub that's neither the spec nor IWO2-true. This loop replaces it with the IWO2-port persona and persists it through the existing `/llm/configs` PATCH path so operators can keep tuning.

### 4. Output → Workspace routing UX — **D (both)**

Auto-save every output_package into a tenant-default `Outputs/` workspace folder when it's produced; the operator can move/rename/reorganize from the Output Package detail surface or the Workspace UI.

**Submit Order does NOT require a folder pick.** The default path is always populated; folder pick is operator-deferred.

Implementation:
- Tenant default folder seeded as `Outputs/` per tenant (idempotent, runs in seed loader).
- `produce_output_package` resolves the tenant default folder and writes the workspace_folder_id onto the artifact created from the package.
- Output Package detail surface gets a "Move to folder…" action.

### 5. Audit vocabulary lock — **Yes, locked in this loop**

The 9 workspace events are added and locked as `PRE_BETA_PHASE_DELTA_AUDIT_EVENTS`. Cardinality bump 91 → 100 recorded explicitly. Contract snapshot updated in the same commit series.

Locked events:
```
folder.created
folder.renamed
folder.moved
folder.deleted
file.created
file.renamed
file.moved
file.deleted
file.saved_from_output
```

Naming uses the `<noun>.<verb>` pattern from the existing vocabulary; `file.saved_from_output` is the audit anchor for the auto-routing path in (4).

## Stage 0 question matrix (CODEX directive § A–E)

### A. Workspace parity

| Question | Answer |
|---|---|
| Exact IWO2 behavior, or IWO2-equivalent + improved IWO3 UX? | **IWO2-equivalent + improved IWO3 UX.** Preserve operator mental model; refine where IWO3's tenant + RLS + audit posture allows a cleaner story. |
| Authoritative workspace root model | **Per tenant.** One workspace tree per `client_id`, rooted at a tenant-default folder. No per-operator or per-WO subdivision in this loop (Beta scope). |
| File types that must preview in this loop | **txt / md / json / csv / png / jpg.** PDFs render as a download/external link only this loop. PPTX preview is Beta scope. |
| Is upload mandatory in this loop? | **Yes — basic single-file upload.** Workspace without upload is half a Workspace; the directive's "file create" outcome implies it. Multi-file batch upload is Beta scope. |

### B. Aiden persona

| Question | Answer |
|---|---|
| Port IWO2 prompt nearly verbatim? | **Port behavior verbatim where it lives in IWO2 runtime; adapt naming/IDs for IWO3 (`aiden_tier_1` instead of IWO2's older role keys).** Spec is the guardrail per (3). |
| Casual chat + routing share one persona contract? | **Yes.** One Aiden, two output modes: conversational (`assistant_reply`) or structured-decision (`work_order_brief` / `workflow_brief` / `clarification`). The persona prompt explicitly tells Aiden which mode to choose. |
| Non-negotiable IWO2 traits | (1) Identity is "Aiden, the Tier-1 orchestrator"; (2) decisive but conversational tone; (3) does not produce content itself; (4) speaks in operator's voice about IWO platform concepts (work orders, sub-agents, output packages, handoffs); (5) escalates / asks for clarification rather than guessing on ambiguous intake; (6) acknowledges process state ("created", "running", "completed") rather than feigning content output. |

### C. Product-quality scope

| Question | Answer |
|---|---|
| Mandatory pages this loop | **Workspace, Chat with Aiden, Work Orders, Output Packages, Handoffs, Aiden Settings, Sub-Agents.** Same set as the directive's Stage 5 must-have list. |
| Pages that may stay secondary | Sandbox, Design Lab partial, System Health, Tier Overview, Pipelines, User Management, Tools. They stay placeholder per ADR-024 deferred list, but get an honest "in development" pattern (consistent empty state, link to the right Beta-track surface). |
| Minimum visual/design standard | **At least IWO2 baseline** measured via side-by-side comparison against `localhost:5001`. Goal is "no longer feels like a messy scaffolded shell" per Success Condition. |

### D. Output/process path

| Question | Answer |
|---|---|
| Canonical operator path after create+run | Submit / Chat → Aiden brief → Create+run → success message with three direct actions (Open WO / Open Output Package / Open Workspace) → Workspace shows the auto-saved artifact in `Outputs/` → Output Package detail page shows the same artifact + handoff state. |
| Mandatory follow-up prompts | The 6 in the directive plus the 8 already verified in γ.2: `where is the output / show me the result / open it / what happened / did it finish / where do I find it / how did it go / where is the result`. The persona update in Stage 2 takes ownership of these so the regex resolver becomes a fallback, not the primary. |

### E. Runtime/process

| Question | Answer |
|---|---|
| Single supported local runner | `bash scripts/iwo3.sh up\|down\|status\|restart` from γ.6. Loop δ refines this only if a real gap surfaces; no rewrite. |
| One start/restart/status path standardized | **Yes** — already true post-γ. This loop verifies it stays true after the Workspace + persona changes, not redesigned. |

## Phase plan (executive summary)

| Phase | Headline | Acceptance link |
|-------|----------|-----------------|
| δ.0 | This prestart doc + IWO2 reference capture | gating |
| δ.1 | Workspace schema — `workspace_folders` table + `artifacts.workspace_folder_id` + RLS + tenant default folder seed + migration 0014 | Gates 3, 5 |
| δ.2 | Workspace backend — CRUD routes (`/workspace/folders`, `/workspace/files`) + 9 audit events + permission keys + RBAC | Gates 3, 5 |
| δ.3 | Output → Workspace auto-routing — `produce_output_package` writes artifact into `Outputs/`; `file.saved_from_output` audit | Gate 5 |
| δ.4 | Workspace UI — drag-and-drop tree (`streamlit-sortables` evaluation) + folder/file CRUD + upload + previews | Gates 3, 4 |
| δ.5 | Aiden persona port — IWO2 runtime prompt → `llm_configs.system_prompt`; conversational mode integrated; cleanup of γ-era regex shortcuts to be persona-mediated | Gates 1, 2 |
| δ.6 | Work Order trust completion v2 — beyond the γ.4 Aiden decision card; clearer current-state narrative; tightened Outputs tab | Gate 8 |
| δ.7 | Sub-page product quality uplift — Output Packages / Handoffs / Aiden Settings / Sub-Agents to IWO2 baseline | Gate 10 |
| δ.8 | Closeout — Loop record + 5 stage records + risk register + runbook update + CODEX review note + final CI green + push | Gates 11, 12 |

## Risks acknowledged at plan time

1. **`streamlit-sortables` may not natively support nested-folder + file-into-folder semantics.** Mitigation: evaluate first; if needed, fall back to `streamlit-tree-select` or compose two `streamlit-sortables` lists with explicit "drop zones" per folder. React custom component only if both fail.
2. **IWO2 Aiden prompt is operator-tuned over time.** Mitigation: I'll capture the current IWO2 runtime prompt as the canonical source for this loop; spec serves as guardrail.
3. **Audit event cardinality 91 → 100** trips the contract snapshot test; mitigation handled in the same commit series per audit-lock discipline.
4. **Permission vocabulary may need 3–4 new keys** (`workspace:read`, `workspace:write`, `workspace:upload`, `workspace:delete`). If so, role-permission mappings + cardinality assertions get bumped in lockstep with the migration. Cosmetic but requires same-commit discipline as α.5/β.6 channel permissions.
5. **Drag-drop dep adds to `pyproject.toml`** — must be pinned, optional in CI if it doesn't work in the headless harness, and documented in the runbook.

## Definition of done (mirroring directive)

- All 11 must-have acceptance gates pass.
- Should-have items either complete or documented with rationale.
- No Beta items pulled into scope.
- All 5 stage records + the loop record produced.
- Risk register bumped to v0.2.3.
- Runbook updated.
- CODEX review note written.
- CI green; live verification re-run.

## Operator-facing path after loop close

1. `bash scripts/iwo3.sh up`
2. Open `localhost:8501`
3. Workspace shows real folders + files with drag-drop, including auto-saved outputs.
4. Chat with Aiden replies in IWO2-true voice across casual + concrete prompts.
5. Create+run produces an output that lands in Workspace `Outputs/` automatically and is reachable from the chat success message.
6. Work Order detail shows what Aiden decided, what ran, what was produced, current state, audit trail — all on one page without stitching.

## Open architect questions (carried forward, not blocking δ)

The 8 open questions from `IWO3_PRE_BETA_GAP_CLOSURE_CODEX_REVIEW_REPORT_v0.1.0.md` and `CLAUDE_HANDBACK_ALPHA_CLOSEOUT_2026-04-25.md` remain Beta-track. They do not block this loop but should be answered before MegaLoop Beta opens.

## Authorization

Architect Stage 0 answers received 2026-04-25. Loop δ execution proceeds under dangerous mode through to closeout per the directive's "DANGEROUS MODE AUTHORITY" section.
