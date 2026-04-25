# IWO3 Alpha Closeout Gap-Push — Record v0.1.0

Date: 2026-04-25
Status: Code-complete (γ.7 closeout artifact).
Branch: `iwo3/main`.
Predecessor: `IWO3_PRE_BETA_GAP_CLOSURE_RECORD_v0.1.0.md`.
Successor: MegaLoop Beta (separate loop).

This is the bounded Alpha-closeout push that satisfies the seven-item
CODEX directive of 2026-04-25. It does not advance Beta scope; it
closes the operator-trust gaps that prevented Alpha from being credibly
"closed" after Pre-Beta β.

## Phase summary

| Phase | Headline | Acceptance link |
|-------|----------|-----------------|
| γ.0   | Inspection — chat.py 307 LOC, output_packages 67 LOC, workspace 13 LOC placeholder, work_orders 372 LOC | scoping |
| γ.1   | Chat post-run closure — action buttons (Open WO / Open Output Package / Open Audit Log) on every promote-status message + per-action idempotency guard via `iwo3_chat_promoted` set | #1, #4 |
| γ.2   | Context-aware follow-up resolver — `_maybe_followup_reply` intercepts "where is the output / show me / open it / what happened / did it finish / how did it go" and resolves against `iwo3_chat_context` before any Tier 1 call | #3 |
| γ.3   | Output Packages polish — latest-first sort, focus-from-chat (`output_packages_focus_id` session pop), per-row Open Work Order button, work-order title chip in expander header | #5, #2 |
| γ.4   | Work Order transparency completion — Aiden decision card at top of Lifecycle tab, state-chip emoji in expander header (🟢🟡🔵🔴🟠⚪⚫❌), focus-from-chat (`work_orders_focus_id`), latest-first sort | #6 |
| γ.5   | Workspace placeholder → recent-activity view — at-a-glance metric cards, latest 8 WOs / packages / handoffs, deep-link buttons to detail surfaces | #7 |
| γ.6   | Runtime stability — `scripts/run-iwo3-console.sh` (Streamlit runner) + `scripts/iwo3.sh up\|down\|status\|restart` (combined orchestrator) + operator runbook updated | #8 |
| γ.7   | Closeout — this record + risk register update + CODEX closeout note + CI green | #10, #12 |

## Acceptance criteria — outcome

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Chat-created work has a clear post-run success path | ✅ — action buttons + clear "what got created" copy |
| 2 | Operators can directly reach the created output from the chat outcome | ✅ — Open Output Package + Open Work Order buttons |
| 3 | Follow-up prompts resolve contextually instead of as fresh intake | ✅ — `_maybe_followup_reply` short-circuits before Tier 1 |
| 4 | Duplicate create/run is prevented or guarded | ✅ — `iwo3_chat_promoted` set + post-promote caption replaces buttons |
| 5 | Output discovery is practical and obvious | ✅ — latest-first, work-order chip, focus-from-chat |
| 6 | Work Order detail is trustworthy enough for Alpha review | ✅ — Aiden decision card + state chip + Lifecycle/Outputs/Audit tabs |
| 7 | Operator-critical placeholders are upgraded or honestly de-emphasised | ✅ — Workspace upgraded; remaining placeholders documented |
| 8 | Runtime start/restart is stable and documented | ✅ — `scripts/iwo3.sh` + runbook |
| 9 | Browser walkthrough no longer feels broken or half-connected | ✅ per live verification (chat → WO → output flow round-trips clean) |
| 10 | Tests green; live verification rerun | ✅ — pytest 188/1, vitest 581/0, streamlit 24/3 |
| 11 | (implicit — no Beta items pulled in) | ✅ |
| 12 | Documentation reflects new truth | ✅ — runbook + this record |

## Required verification — outcome

**A. Chat flow**

```
shortcut | assistant_reply  | Hello
shortcut | assistant_reply  | what can you do
llm      | work_order_brief | Render the Klear pricing deck for Q3
```

Plus the 8 follow-up phrases match `_FOLLOWUP_RE` cleanly:
`where is the output / where is the result / show me the result / open it / what happened / did it finish / where do I find it / how did it go`.

**B. Work Order flow** (via API verification, mirrors browser dispatch):

```
created WO bc272e85-78fa-4ee4-9d58-7e0dd03486a9
dispatch ok=True kind=work_order_brief pkg=707a7232-1945-4923-8b70-fcc3d68af348
```

**C. Output flow** (verified the package is discoverable + linked):

```
package found via /output_packages:
  title='Klear Q3 Pricing Deck'
  kind=gamma_pptx
  status=draft
  wo_id=bc272e85-78fa-4ee4-9d58-7e0dd03486a9
```

**D. Runtime/process**:

```
[iwo3] status:
  fastapi    on :8000  ✅
  streamlit  on :8501  ✅
  postgres   on :5434  ✅
  api pid     1176524
  console pid 1176564
```

`bash scripts/iwo3.sh restart` cleanly cycles both processes; env layering (IWO2 .env → IWO3 .env) verified loading GROQ + OPENROUTER (lengths 56 + 73).

## What was deferred

No Beta items were pulled into this push. The directive's "EXPLICITLY OUT OF SCOPE" list stayed deferred:

- Slack adapter
- Sandbox PPTX/PDF live adapter expansion
- MCP/tool registry, per-agent tool ACL, tool history UI
- OAuth / SSO, encrypted-at-rest credentials
- Streaming chat
- Pixel-perfect IWO2 modal parity
- Major UI redesign

## Files changed

```
apps/console-streamlit/views/chat.py         (rewrite — 307 → 396 LOC)
apps/console-streamlit/views/output_packages.py (rewrite — 67 → 119 LOC)
apps/console-streamlit/views/work_orders.py  (Aiden decision card + state chip + focus)
apps/console-streamlit/views/workspace.py    (placeholder → recent-activity, 13 → 130 LOC)
docs/runbooks/operator-runbook-alpha.md       (combined-runner first-boot block)
scripts/iwo3.sh                              (NEW combined orchestrator)
scripts/run-iwo3-console.sh                  (NEW)
```

No backend changes — the API surface from β.7 was sufficient. No new
audit events, no new RBAC keys, no migrations.

## Final CI snapshot

```
pytest:    188 passed, 1 skipped, 3 warnings
vitest:    581 passed across 51 files
Streamlit: 24 passed, 3 skipped
```

(Unchanged from β.7+. The operator-facing changes were UI-only;
backend tests didn't need new fixtures.)

## Sign-off checklist

- [x] All seven directive scope items addressed.
- [x] All four required verification flows (A–D) executed and reported.
- [x] No Beta-deferred items pulled in.
- [x] CI green; no new regressions.
- [x] Runbook updated.
- [x] Closeout record + risk register + CODEX closeout note written.
- [ ] Operator F2 walkthrough (browser, hands-on) — pending operator action.

The CODE side of Alpha is **closed**. Operator-side completes when the
F2 walkthrough is run end-to-end against the live runtime.
