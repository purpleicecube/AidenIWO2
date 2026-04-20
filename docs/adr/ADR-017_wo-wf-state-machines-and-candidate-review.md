# ADR-017 — WO / WF lifecycle state machines + candidate review semantics

Date: 2026-04-20
Status: Accepted (Loop 6 Phase 6.3 closeout)
Predecessors: ADR-011 (WO/WF schema; Loop 3 deferred state-machine
semantics to Loop 6), ADR-012 (output packages + adapter registry;
candidate shape locked in Phase 3.2 hybrid), ADR-014 + ADR-015 + ADR-016.

## Context

Loop 3 Phase 3.1 persisted `status` fields on work_orders,
workflows, workflow_executions, workflow_step_runs, and
execution_cycles, but deferred the transition rules: Loop 3 §Q2
confirmed state-machine semantics should land in Loop 6 so the
runtime primitives could stabilise first.

Loop 3 Phase 3.2 locked the candidate-review minimal shape
(`output_handoffs.candidate_status` + `candidate_group_id`,
hybrid per approval memo §Q5). Loop 6 adds the operator-action
flow on top of that shape.

Loop 4 added RBAC + RLS + the permission vocabulary that gates
privileged mutations; Loop 5 froze the contract surface. Loop 6
is the first loop that consumes both: every transition goes
through `requirePermission` and writes an audit row with the
locked Loop 6 Phase 1 event vocabulary.

## Decision

Four declarative transition tables + five transition helpers +
two candidate-review helpers ship in Loop 6.

### Transition tables (declarative, TS canonical, Python parity)

Located at `packages/contracts/wo-wf/state_machines.ts` with
byte-identical mirror at
`apps/api-fastapi/contracts/state_machines.py`. Parity enforced
by `tests/contract/state-machine-parity.test.ts`.

**work_orders.status** — 21 transitions across 9 states:

```
pending        → processing | deferred | cancelled
processing     → completed | done | blocked | awaiting_operator | failed | cancelled
blocked        → processing | cancelled | failed
awaiting_operator → processing | cancelled | failed
deferred       → processing | cancelled
completed      → processing   (reopen via cycle)
done           → processing   (reopen via cycle)
failed         → processing   (reopen via cycle)
processing     → blocked      (watchdog-expire — separate spec)
cancelled      → (hard terminal; no outgoing)
```

**workflows.status** — 4 transitions (active ↔ paused, each →
archived terminal).

**workflow_executions.status** — 6 transitions (pending/running
→ completed | failed | cancelled, plus failed → running reopen
which flags `requiresCycle=true` as documentation for Loop 9+
orchestration — Phase 6.2 does not open a cycle row here because
execution_cycles is WO-scoped in the current schema; see R-009
in the CODEX log).

**workflow_step_runs.status** — 5 transitions (pending → running
→ completed | failed | skipped; pending → skipped direct).

Total: 36 transitions. Every spec carries:

- `requires: readonly string[]` — permission keys the actor must
  hold (all of them). Reopen paths require both
  `execution_cycle:reopen` + `work_order:update` per §Q2 default.
- `event: string` — the `AUDIT_EVENTS` key to emit.
- `requiresCycle?: boolean` — true iff the transition opens a new
  `execution_cycles` row (WO reopen + watchdog only).

### Transition helpers (runtime entry points)

At `packages/contracts/wo-wf/transitions.ts`:

- `transitionWorkOrder(client, { workOrderId, clientId,
  actorUserId, to, reason? })` — general-purpose WO state change.
  Picks the FIRST matching spec from the table, so processing →
  blocked resolves to the "regular block" spec with
  `work_order.blocked` event.
- `watchdogExpireWorkOrder(client, { workOrderId, clientId,
  actorUserId, reason })` — dedicated watchdog path. Selects the
  watchdog spec explicitly so manual blocks and automated
  watchdog blocks are distinguishable at the audit layer.
- `transitionWorkflow`, `transitionWorkflowExecution`,
  `transitionWorkflowStepRun` — analogous helpers for the other
  three state machines.

Every helper:

1. Loads current row (tenant-scoped where possible).
2. `describeTransition` — illegal transitions throw
   `IllegalTransition` before any DB write.
3. Calls `requirePermission` for every permission in `requires`.
4. Updates status.
5. Inserts `execution_cycles` row if `requiresCycle` (WO only).
6. Writes exactly one audit row with `{machine, from, to, reason,
   cycleId?}` metadata.

### Candidate-review helpers (reviewer-gated)

At `packages/contracts/wo-wf/candidate_review.ts`:

- `selectCandidate(client, { handoffId, clientId, actorUserId,
  reason? })` — requires `output_candidate:select`. Marks the
  chosen handoff `candidate_status='selected'` (with
  `selected_at` + `selected_by_user_id`); auto-rejects every
  sibling in the same `candidate_group_id`; validates the parent
  `output_packages` row (`status='validated'`). Writes one
  `output_candidate.selected` + N `output_candidate.rejected` + 1
  `output_package.validated` audit rows.
- `rejectCandidate(client, { handoffId, clientId, actorUserId,
  reason? })` — requires `output_candidate:reject`. Marks a
  single handoff rejected without touching siblings or parent
  package. Writes one `output_candidate.rejected` audit row.

Neither operator nor agent_system holds these permissions by
default (§Q2 revised grants); candidate review is reviewer-only
plus admin/owner by default.

### Deliberately NOT in Loop 6

- **Scheduled watchdog job.** `watchdogExpireWorkOrder` is a
  helper; Loop 9+ orchestration adds the scheduled loop that
  invokes it. §Q1 default.
- **Workflow_execution retry lineage.** The `requiresCycle` flag
  on failed → running is documentation. Loop 9+ may add a
  per-execution cycle mechanism.
- **Cross-WO workflow chaining.** Out of scope; belongs in the
  workflow engine.
- **FastAPI / Streamlit surfaces.** Loops 7 + 8 consume these
  helpers; they are not added here.

## Consequences

**Positive**

- Every state change flows through one pipeline: validate →
  authz → update → cycle-if-needed → audit. No handler invents
  its own state transition.
- Declarative tables (not hand-coded if/else) make new states
  and new transitions a data change + test update, not a
  refactor. Python parity keeps FastAPI (Loop 7) from drifting.
- Reopen semantics are captured in one place: the transition
  spec says `requiresCycle=true`, the helper opens the cycle row
  with the right trigger, audit records the lineage. A future
  operator asking "why did this WO restart?" gets a
  machine-readable answer.
- Candidate review ships the operator-facing flow without
  introducing new state on the packages/handoffs — it works on
  the Phase 3.2 minimal shape.

**Negative**

- 21 WO transitions is a lot. Adding a new state or removing one
  is a breaking change that touches the TS table, the Python
  mirror, the snapshot, and every downstream helper that pattern-
  matches on `from`/`to`. The lint rule for contract surface
  drift (ADR-016) helps but doesn't fully prevent this.
- First-match semantics on `describeTransition` means the
  watchdog spec is ordered AFTER the regular block spec in the
  table. A refactor that reorders the table will flip general
  `transitionWorkOrder` behaviour for processing → blocked.
  Mitigated by `watchdogExpireWorkOrder` as a named helper that
  picks the watchdog spec explicitly.
- `workflow_step_runs` has no direct client_id column, so the
  helper's UPDATE carries a lint-bypass annotation. The RLS
  parent-JOIN policy (Phase 4.3) + the `requirePermission` gate
  keep the tenant boundary intact.

## Alternatives considered

- **Event sourcing instead of status columns** — rejected for
  Loop 6 scope; the existing tables already carry `status` and
  retrofitting event sourcing would be a multi-loop rewrite.
- **Generic `transition(client, machine, id, to, ...)` single
  helper** — rejected because each machine has a different
  tenant-lookup path (WO/WF/execution carry client_id; step_runs
  don't) and a different cycle-insert behaviour.
- **Let callers pass a `metadata` blob into transitions** —
  rejected for Phase 6.2 to keep the helper signatures narrow.
  Loop 7 FastAPI handlers that need richer context (e.g.
  "reopen because customer complained via Slack") can encode that
  into the `reason` string. A future loop may extend the helper
  to take optional structured metadata if genuinely needed.

## References

- `IWO3_LOOP_6_SCOPE_PROPOSAL_v0.1.0.md` §3
- Loop 6 Phase 6.1 commit `26297e5` / CI run `24658515775`
- Loop 6 Phase 6.2 commit `6e677a3` / CI run `24658898993`
- `packages/contracts/wo-wf/state_machines.ts` +
  `transitions.ts` + `candidate_review.ts`
- `apps/api-fastapi/contracts/state_machines.py` +
  `state_machines_cli.py`
- Risk register v0.1.9 (R09 watchdog timing-window; R10
  candidate-review race — both mitigated)
