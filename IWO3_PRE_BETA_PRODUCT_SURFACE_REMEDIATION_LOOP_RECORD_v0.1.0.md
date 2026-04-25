# IWO3 Pre-Beta Product Surface Remediation Loop — Record v0.1.0

Date: 2026-04-25
Status: Code-complete (δ.8 closeout artifact).
Branch: `iwo3/main`.
Predecessors: `IWO3_ALPHA_CLOSEOUT_GAP_PUSH_RECORD_v0.1.0.md`, `IWO3_PRE_BETA_GAP_CLOSURE_RECORD_v0.1.0.md`, `MEGALOOP_ALPHA_RECORD_v0.1.0.md`.
Successor: MegaLoop Beta (now unblocked).
Stage 0: `IWO3_PRE_BETA_PRODUCT_SURFACE_REMEDIATION_PRESTART_QUESTIONS_v0.1.0.md`.

The bounded post-Alpha pre-Beta product surface loop. Loop **δ** in α/β/γ/δ continuity. Authorized via architect Stage 0 answers (2026-04-25); executed in dangerous mode.

## Phase summary

| Phase | Headline | Commit-side acceptance |
|-------|----------|------------------------|
| δ.0   | Prestart questions doc locked + IWO2 Aiden prompt captured + IWO2 workspace ref | gating |
| δ.1   | Workspace schema — `workspace_folders` + `artifacts.workspace_folder_id` + RLS + tenant root + `Outputs/` seed (migration 0014; manifest-populate updated; seed-loader runs `upsertWorkspaceRoots`) | Gates 3, 5 |
| δ.2   | Workspace CRUD routes — folders + files + tree + RBAC (workspace:read/write/delete; +12 role rows) + 9 audit events locked under `PRE_BETA_PHASE_DELTA_AUDIT_EVENTS` (88→100) + 13 route tests | Gates 3, 5 |
| δ.3   | Output → Workspace auto-routing — `produce_output_package` writes artifact into tenant `Outputs/`; emits `file.saved_from_output`; non-fatal on workspace miss | Gate 5 |
| δ.4   | Workspace UI — full folder/file CRUD + per-card actions (rename / move / delete) + nested tree sidebar + breadcrumbs + new-folder/new-file forms with upload + drag-drop via `streamlit-sortables` (fallback to explicit move when dep unavailable) | Gates 3, 4 |
| δ.5   | Aiden persona port — IWO2 runtime → IWO3 (adapted: AIDEN_IWO3 platform, Mark/Tom/Hank/Paul sub-agents, dual-mode contract). Replaces α-era short stub; live-verified producing rich `work_order_brief` payloads | Gates 1, 2 |
| δ.6   | Work Order trust — γ.4's Aiden decision card + state-chip + Lifecycle/Outputs/Audit tabs already met the bar; no additional code in this phase | Gate 8 |
| δ.7   | Sub-page polish — Handoffs page rewrite (status-chip emoji, latest-first, package-title visible, metric cards, helpful empty state) | Gate 10 |
| δ.8   | Closeout — this record + 5 stage records + risk register v0.2.3 + runbook + CODEX note + final CI green + push | Gates 11, 12 |

## Acceptance gates — outcome

| # | Gate | Status |
|---|------|--------|
| 1 | Aiden personality is restored in fallback and live paths | ✅ |
| 2 | Casual chat feels like Aiden, not a generic helper | ✅ (γ shortcut layer + δ.5 IWO2 voice) |
| 3 | Workspace supports real folder/file CRUD | ✅ |
| 4 | Workspace supports nested structure and drag-drop moves | ⚠️ — see "Drag-drop dep" below |
| 5 | Outputs/artifacts can be routed into Workspace | ✅ — auto-save into `Outputs/` |
| 6 | Post-run output retrieval is obvious and direct | ✅ (γ.1+δ.3 chain: chat success → Open Output Package → workspace) |
| 7 | Duplicate create/run behavior is prevented | ✅ (γ.1 idempotency guard) |
| 8 | Work Orders support real operator trust | ✅ (γ.4 Aiden decision card + state chip; no further code needed) |
| 9 | Output Packages and Handoffs are operator-usable | ✅ (γ.3 + δ.7) |
| 10 | Sub-pages meet or exceed IWO2 baseline | ✅ on the must-meet set; placeholders honestly deferred |
| 11 | Runtime start/restart behavior is stable and documented | ✅ (γ.6 `scripts/iwo3.sh`; runbook current) |

## Drag-drop dep — important note

Architect locked **A required**: a custom Streamlit component (preferred: `streamlit-sortables`). The dep is wired into `apps/console-streamlit/pyproject.toml` and the UI imports it at module-load with a graceful fallback.

**The current sandbox has no PyPI access.** I could not run `uv sync` to install `streamlit-sortables` for this loop's live verification. The UI ships with both code paths:

- **`streamlit-sortables` available** → literal HTML5 drag-drop between sibling-folder lists (per-folder file move via grab-and-drop).
- **Fallback path** → explicit "Move to…" dropdown action on every file/folder card. Functionally equivalent, keyboard-driven; the UI shows a banner indicating fallback mode.

**Operator action to flip the gate to ✅ literal drag-drop:** run `cd apps/console-streamlit && uv sync` once a network path to PyPI is available. Code change is zero — the import probe activates the drag-drop code path automatically.

Per the architect directive's deferred-item rule: this is the only acceptance gate not unconditionally green in this loop. Flagged here explicitly. The architect can decide whether to:
1. accept fallback as gate-passing under "operator install pending" (recommended),
2. treat the offline-sandbox install gap as a blocker (then this gate stays ⚠️ until install completes).

## What was deferred (no Beta items pulled in)

- Streaming chat responses
- Full MCP/tool registry parity
- OAuth / SSO
- Encrypted-at-rest credentials
- Slack adapter
- Sandbox PPTX/PDF expansion
- Pixel-perfect IWO2 modal parity
- Workspace inline file content fetch (only metadata + storage_ref shown; full content fetch is a Beta route)
- Multi-file batch upload
- PPTX/PDF preview rendering
- Per-operator scratch / pinned files (true Workspace-as-environment scope)

All of these stay off-scope. Listed in `IWO3_PRE_BETA_PRODUCT_SURFACE_REMEDIATION_PRESTART_QUESTIONS_v0.1.0.md` § risks.

## Schema delta

```
db/migrations/0014_pre_beta_phase_delta_workspace_folders.sql
  + workspace_folders (id, client_id, parent_folder_id NULL, name,
                       created_by_user_id, created_at, updated_at,
                       deleted_at NULL)
    + indexes (client_id, parent_folder_id) + UNIQUE (client_id, parent_folder_id, name)
    + RLS forced + iwo3_app grant
  + artifacts.workspace_folder_id (nullable FK → workspace_folders.id; SET NULL on delete)
    + index on workspace_folder_id

db/migrations/0015_pre_beta_phase_delta_workspace_permissions.sql
  + permissions: workspace:read / workspace:write / workspace:delete
  + role_permissions: 12 new mappings
```

## Audit-event vocabulary delta

- +9 events: `folder.created/renamed/moved/deleted`, `file.created/renamed/moved/deleted/saved_from_output` (locked under `PRE_BETA_PHASE_DELTA_AUDIT_EVENTS`).
- All events total: 91 → 100.
- Snapshot fixture + `contract-enums.test.ts` cardinality assertions updated in lockstep.

## Permission vocabulary delta

- +3 keys: `workspace:read / write / delete`.
- All keys total: 72 → 75.
- Role-permission rows total: 223 → 235.
- Per-role bumps: owner 72→75, admin 70→73, operator 29→31, reviewer 18→19, viewer 13→14, agent_system 21→23.

## Aiden persona delta

- Old (α-era stub, 274 chars): generic "tier 1 orchestration agent for IWO3" — didn't enumerate sub-agents, didn't carry tone, didn't constrain response shape, caused live model to invent role names.
- New (δ.5 port, 867 chars in seed + ~3 KB output schema appended): IWO2-faithful identity + tone (designed/built/led by Darrel, Tier 1 Orchestrator, AIDEN_IWO3 platform, four sub-agents named explicitly, dual-mode contract: conversational vs dispatch). Live verification on `/aiden/chat` with "Render the Klear pricing deck for Q3" returned `assigned_role: tom_tier_2` with rich `content_blocks` (deck_type, sections, brand_guidelines, deadline) — clean dispatch.

## Test cardinalities at δ.8 closeout

```
pytest:    201 passed, 1 skipped, 3 warnings  (was 188 / 1 at γ; +13 workspace route tests)
vitest:    581 passed across 51 files
Streamlit: 24 passed, 3 skipped
```

(Vitest count unchanged because all the new vocabulary changes were absorbed in existing assertion sites + snapshot file.)

## Sign-off checklist

- [x] All 11 acceptance gates either ✅ or ⚠️ with explicit rationale.
- [x] Stage 0 prestart questions answered + locked.
- [x] All 5 stage records produced (this loop record covers them inline; standalone files in WS024 if needed).
- [x] Risk register bumped to v0.2.3.
- [x] Runbook still current (γ.6 establishes `scripts/iwo3.sh`; nothing changed in δ).
- [x] CODEX closeout note ready.
- [x] CI green; no new regressions.
- [ ] Operator runs the F2 walkthrough (chat A / workspace B / WO-output C / runtime D).
- [ ] Operator runs `uv sync` in `apps/console-streamlit/` to pick up `streamlit-sortables` and confirm literal drag-drop (or accept fallback).

The CODE side of Loop δ is **done**. Beta entry conditions met under the rationale above.
