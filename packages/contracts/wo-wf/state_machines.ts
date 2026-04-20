/**
 * Loop 6 Phase 6.1 — lifecycle state machines for WO / WF / executions
 * / step runs.
 *
 * Declarative transition tables keyed by `(state_machine, from, to)`.
 * Each transition carries:
 *   - `requires`       — the permission keys the actor must hold (any caller
 *                        missing any of these fails closed via
 *                        `requirePermission`). Multi-permission cases
 *                        (e.g. reopen = `execution_cycle:reopen` +
 *                        `work_order:update`) are declared here so the
 *                        Phase 6.2 transition helpers don't invent gates.
 *   - `event`          — the `AUDIT_EVENTS` key to emit. 12 new Loop 6
 *                        Phase 1 events are locked upfront (§Q1 precedent
 *                        from Loop 4).
 *   - `requiresCycle`  — true iff the transition inserts a new
 *                        `execution_cycles` row. Used by terminal →
 *                        processing reopen paths + watchdog expire.
 *
 * Policy guardrails (per IWO3_LOOP_6_SCOPE_PROPOSAL §7 defaults):
 *   - Reopen from any terminal requires BOTH `execution_cycle:reopen` +
 *     `work_order:update` (or the workflow equivalents).
 *   - Watchdog expire is an agent_system-only path; permission list
 *     reflects that.
 *   - `cancelled` is terminal — no transitions out. If work needs to
 *     restart after cancellation, operators open a new WO.
 *
 * This module is TS-canonical; `apps/api-fastapi/contracts/state_machines.py`
 * mirrors it byte-for-byte. Parity is enforced by
 * `tests/contract/state-machine-parity.test.ts`.
 */

import { AUDIT_EVENTS } from "../audit/events";

export type StateMachineKey =
  | "work_order"
  | "workflow"
  | "workflow_execution"
  | "workflow_step_run";

export interface TransitionSpec {
  readonly from: string;
  readonly to: string;
  readonly requires: readonly string[];
  readonly event: string;
  readonly requiresCycle?: boolean;
}

// ── work_orders.status ────────────────────────────────────────────────
// 9 states: pending, processing, blocked, awaiting_operator, completed,
// done, failed, deferred, cancelled.
// Terminal: completed, done, failed, cancelled. (cancelled = true terminal;
// others may reopen via execution_cycle.)
export const WORK_ORDER_TRANSITIONS: readonly TransitionSpec[] = [
  // pending → …
  {
    from: "pending",
    to: "processing",
    requires: ["work_order:submit"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  {
    from: "pending",
    to: "deferred",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  {
    from: "pending",
    to: "cancelled",
    requires: ["work_order:cancel"],
    event: AUDIT_EVENTS.WORK_ORDER_CANCELLED,
  },
  // processing → …
  {
    from: "processing",
    to: "completed",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  {
    from: "processing",
    to: "done",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  {
    from: "processing",
    to: "blocked",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_BLOCKED,
  },
  {
    from: "processing",
    to: "awaiting_operator",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  {
    from: "processing",
    to: "failed",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  {
    from: "processing",
    to: "cancelled",
    requires: ["work_order:cancel"],
    event: AUDIT_EVENTS.WORK_ORDER_CANCELLED,
  },
  // blocked → …
  {
    from: "blocked",
    to: "processing",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_UNBLOCKED,
  },
  {
    from: "blocked",
    to: "cancelled",
    requires: ["work_order:cancel"],
    event: AUDIT_EVENTS.WORK_ORDER_CANCELLED,
  },
  {
    from: "blocked",
    to: "failed",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  // awaiting_operator → …
  {
    from: "awaiting_operator",
    to: "processing",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  {
    from: "awaiting_operator",
    to: "cancelled",
    requires: ["work_order:cancel"],
    event: AUDIT_EVENTS.WORK_ORDER_CANCELLED,
  },
  {
    from: "awaiting_operator",
    to: "failed",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  // deferred → …
  {
    from: "deferred",
    to: "processing",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  },
  {
    from: "deferred",
    to: "cancelled",
    requires: ["work_order:cancel"],
    event: AUDIT_EVENTS.WORK_ORDER_CANCELLED,
  },
  // Reopen paths — terminal (non-cancelled) back to processing via a
  // new execution_cycle. Requires both execution_cycle:reopen AND
  // work_order:update per §Q2 default.
  {
    from: "completed",
    to: "processing",
    requires: ["execution_cycle:reopen", "work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_REOPENED,
    requiresCycle: true,
  },
  {
    from: "done",
    to: "processing",
    requires: ["execution_cycle:reopen", "work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_REOPENED,
    requiresCycle: true,
  },
  {
    from: "failed",
    to: "processing",
    requires: ["execution_cycle:reopen", "work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_REOPENED,
    requiresCycle: true,
  },
  // Watchdog expire — automation identity only. Forces blocked with a
  // cycle row recording the timer breach.
  {
    from: "processing",
    to: "blocked",
    requires: ["work_order:update"],
    event: AUDIT_EVENTS.WORK_ORDER_WATCHDOG_EXPIRED,
    requiresCycle: true,
  },
];

// ── workflows.status ──────────────────────────────────────────────────
// 3 states: active, paused, archived. archived is terminal.
export const WORKFLOW_TRANSITIONS: readonly TransitionSpec[] = [
  {
    from: "active",
    to: "paused",
    requires: ["workflow:update"],
    event: AUDIT_EVENTS.WORKFLOW_PAUSED,
  },
  {
    from: "paused",
    to: "active",
    requires: ["workflow:update"],
    event: AUDIT_EVENTS.WORKFLOW_RESUMED,
  },
  {
    from: "active",
    to: "archived",
    requires: ["workflow:update"],
    event: AUDIT_EVENTS.WORKFLOW_TRANSITIONED,
  },
  {
    from: "paused",
    to: "archived",
    requires: ["workflow:update"],
    event: AUDIT_EVENTS.WORKFLOW_TRANSITIONED,
  },
];

// ── workflow_executions.status ────────────────────────────────────────
// 5 states: pending, running, completed, failed, cancelled.
// Terminal: completed, cancelled. failed may reopen via a new cycle.
export const WORKFLOW_EXECUTION_TRANSITIONS: readonly TransitionSpec[] = [
  {
    from: "pending",
    to: "running",
    requires: ["workflow_execution:update"],
    event: AUDIT_EVENTS.WORKFLOW_EXECUTION_TRANSITIONED,
  },
  {
    from: "running",
    to: "completed",
    requires: ["workflow_execution:update"],
    event: AUDIT_EVENTS.WORKFLOW_EXECUTION_TRANSITIONED,
  },
  {
    from: "running",
    to: "failed",
    requires: ["workflow_execution:update"],
    event: AUDIT_EVENTS.WORKFLOW_EXECUTION_TRANSITIONED,
  },
  {
    from: "pending",
    to: "cancelled",
    requires: ["workflow:cancel"],
    event: AUDIT_EVENTS.WORKFLOW_EXECUTION_CANCELLED,
  },
  {
    from: "running",
    to: "cancelled",
    requires: ["workflow:cancel"],
    event: AUDIT_EVENTS.WORKFLOW_EXECUTION_CANCELLED,
  },
  // Reopen: failed → running via a new execution_cycle.
  {
    from: "failed",
    to: "running",
    requires: ["execution_cycle:reopen", "workflow_execution:update"],
    event: AUDIT_EVENTS.WORKFLOW_EXECUTION_TRANSITIONED,
    requiresCycle: true,
  },
];

// ── workflow_step_runs.status ─────────────────────────────────────────
// 5 states: pending, running, completed, failed, skipped.
// Terminal: completed, failed, skipped.
export const WORKFLOW_STEP_RUN_TRANSITIONS: readonly TransitionSpec[] = [
  {
    from: "pending",
    to: "running",
    requires: ["workflow_step_run:create"],
    event: AUDIT_EVENTS.WORKFLOW_STEP_RUN_TRANSITIONED,
  },
  {
    from: "running",
    to: "completed",
    requires: ["workflow_step_run:update"],
    event: AUDIT_EVENTS.WORKFLOW_STEP_RUN_TRANSITIONED,
  },
  {
    from: "running",
    to: "failed",
    requires: ["workflow_step_run:update"],
    event: AUDIT_EVENTS.WORKFLOW_STEP_RUN_TRANSITIONED,
  },
  {
    from: "pending",
    to: "skipped",
    requires: ["workflow_step_run:update"],
    event: AUDIT_EVENTS.WORKFLOW_STEP_RUN_TRANSITIONED,
  },
  {
    from: "running",
    to: "skipped",
    requires: ["workflow_step_run:update"],
    event: AUDIT_EVENTS.WORKFLOW_STEP_RUN_TRANSITIONED,
  },
];

// ── Registry — used by validator + parity CLI ─────────────────────────

export const STATE_MACHINES: Readonly<
  Record<StateMachineKey, readonly TransitionSpec[]>
> = {
  work_order: WORK_ORDER_TRANSITIONS,
  workflow: WORKFLOW_TRANSITIONS,
  workflow_execution: WORKFLOW_EXECUTION_TRANSITIONS,
  workflow_step_run: WORKFLOW_STEP_RUN_TRANSITIONS,
};

// ── Pure validator ────────────────────────────────────────────────────

export type TransitionLookupResult =
  | { ok: true; spec: TransitionSpec }
  | { ok: false; reason: "unknown_from" | "illegal_transition" };

export function describeTransition(
  machine: StateMachineKey,
  from: string,
  to: string
): TransitionLookupResult {
  const table = STATE_MACHINES[machine];
  // Special case — same state, trivially legal (no-op update). Does not
  // emit an audit event; callers should guard against no-ops before
  // calling the validator so a no-op doesn't spam the log.
  if (from === to) {
    return { ok: false, reason: "illegal_transition" };
  }
  let sawFrom = false;
  for (const t of table) {
    if (t.from === from) {
      sawFrom = true;
      if (t.to === to) return { ok: true, spec: t };
    }
  }
  return {
    ok: false,
    reason: sawFrom ? "illegal_transition" : "unknown_from",
  };
}

export function legalTransitionsFrom(
  machine: StateMachineKey,
  from: string
): readonly string[] {
  const table = STATE_MACHINES[machine];
  const seen = new Set<string>();
  for (const t of table) {
    if (t.from === from) seen.add(t.to);
  }
  return [...seen].sort();
}

export function isLegalTransition(
  machine: StateMachineKey,
  from: string,
  to: string
): boolean {
  return describeTransition(machine, from, to).ok;
}
