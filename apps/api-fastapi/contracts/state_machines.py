"""Loop 6 Phase 6.1 — Python mirror of WO / WF / execution / step-run
state-machine transition tables.

Byte-identical with the TS canonical source at
``packages/contracts/wo-wf/state_machines.ts``. Parity is enforced by
``tests/contract/state-machine-parity.test.ts`` which spawns
``state_machines_cli.py`` and compares the full transition tables +
permission requirements + audit event names byte-for-byte.

Policy (per IWO3_LOOP_6_APPROVAL_DECISIONS defaults, logged in
IWO3_LOOP_6_SCOPE_PROPOSAL §7):
  - Reopen from any non-cancelled terminal requires BOTH
    ``execution_cycle:reopen`` AND ``work_order:update`` (or the
    workflow-execution equivalents).
  - Watchdog expire is automation-identity. Permission remains
    ``work_order:update`` because agent_system holds it; the event
    name is the distinguishing signal.
  - ``cancelled`` is terminal — no transitions out. Reopen requires a
    new WO/WF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal


StateMachineKey = Literal[
    "work_order",
    "workflow",
    "workflow_execution",
    "workflow_step_run",
]


@dataclass(frozen=True)
class TransitionSpec:
    from_: str
    to: str
    requires: tuple[str, ...]
    event: str
    requires_cycle: bool = False

    def to_dict(self) -> dict:
        return {
            "from": self.from_,
            "to": self.to,
            "requires": list(self.requires),
            "event": self.event,
            # Only emit `requiresCycle` when true so JSON matches the
            # TS side where the property is optional.
            **({"requiresCycle": True} if self.requires_cycle else {}),
        }


# ── work_orders.status ────────────────────────────────────────────────

WORK_ORDER_TRANSITIONS: Final[tuple[TransitionSpec, ...]] = (
    # pending → …
    TransitionSpec(from_="pending", to="processing",
                   requires=("work_order:submit",),
                   event="work_order.transitioned"),
    TransitionSpec(from_="pending", to="deferred",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    TransitionSpec(from_="pending", to="cancelled",
                   requires=("work_order:cancel",),
                   event="work_order.cancelled"),
    # processing → …
    TransitionSpec(from_="processing", to="completed",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    TransitionSpec(from_="processing", to="done",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    TransitionSpec(from_="processing", to="blocked",
                   requires=("work_order:update",),
                   event="work_order.blocked"),
    TransitionSpec(from_="processing", to="awaiting_operator",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    TransitionSpec(from_="processing", to="failed",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    TransitionSpec(from_="processing", to="cancelled",
                   requires=("work_order:cancel",),
                   event="work_order.cancelled"),
    # blocked → …
    TransitionSpec(from_="blocked", to="processing",
                   requires=("work_order:update",),
                   event="work_order.unblocked"),
    TransitionSpec(from_="blocked", to="cancelled",
                   requires=("work_order:cancel",),
                   event="work_order.cancelled"),
    TransitionSpec(from_="blocked", to="failed",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    # awaiting_operator → …
    TransitionSpec(from_="awaiting_operator", to="processing",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    TransitionSpec(from_="awaiting_operator", to="cancelled",
                   requires=("work_order:cancel",),
                   event="work_order.cancelled"),
    TransitionSpec(from_="awaiting_operator", to="failed",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    # deferred → …
    TransitionSpec(from_="deferred", to="processing",
                   requires=("work_order:update",),
                   event="work_order.transitioned"),
    TransitionSpec(from_="deferred", to="cancelled",
                   requires=("work_order:cancel",),
                   event="work_order.cancelled"),
    # Reopen paths — terminal (non-cancelled) → processing via new cycle.
    TransitionSpec(from_="completed", to="processing",
                   requires=("execution_cycle:reopen", "work_order:update"),
                   event="work_order.reopened", requires_cycle=True),
    TransitionSpec(from_="done", to="processing",
                   requires=("execution_cycle:reopen", "work_order:update"),
                   event="work_order.reopened", requires_cycle=True),
    TransitionSpec(from_="failed", to="processing",
                   requires=("execution_cycle:reopen", "work_order:update"),
                   event="work_order.reopened", requires_cycle=True),
    # Watchdog expire path — agent_system writes a cycle row recording
    # the timer breach; status moves to blocked.
    TransitionSpec(from_="processing", to="blocked",
                   requires=("work_order:update",),
                   event="work_order.watchdog_expired",
                   requires_cycle=True),
)


# ── workflows.status ──────────────────────────────────────────────────

WORKFLOW_TRANSITIONS: Final[tuple[TransitionSpec, ...]] = (
    TransitionSpec(from_="active", to="paused",
                   requires=("workflow:update",),
                   event="workflow.paused"),
    TransitionSpec(from_="paused", to="active",
                   requires=("workflow:update",),
                   event="workflow.resumed"),
    TransitionSpec(from_="active", to="archived",
                   requires=("workflow:update",),
                   event="workflow.transitioned"),
    TransitionSpec(from_="paused", to="archived",
                   requires=("workflow:update",),
                   event="workflow.transitioned"),
)


# ── workflow_executions.status ────────────────────────────────────────

WORKFLOW_EXECUTION_TRANSITIONS: Final[tuple[TransitionSpec, ...]] = (
    TransitionSpec(from_="pending", to="running",
                   requires=("workflow_execution:update",),
                   event="workflow_execution.transitioned"),
    TransitionSpec(from_="running", to="completed",
                   requires=("workflow_execution:update",),
                   event="workflow_execution.transitioned"),
    TransitionSpec(from_="running", to="failed",
                   requires=("workflow_execution:update",),
                   event="workflow_execution.transitioned"),
    TransitionSpec(from_="pending", to="cancelled",
                   requires=("workflow:cancel",),
                   event="workflow_execution.cancelled"),
    TransitionSpec(from_="running", to="cancelled",
                   requires=("workflow:cancel",),
                   event="workflow_execution.cancelled"),
    TransitionSpec(from_="failed", to="running",
                   requires=("execution_cycle:reopen",
                             "workflow_execution:update"),
                   event="workflow_execution.transitioned",
                   requires_cycle=True),
)


# ── workflow_step_runs.status ─────────────────────────────────────────

WORKFLOW_STEP_RUN_TRANSITIONS: Final[tuple[TransitionSpec, ...]] = (
    TransitionSpec(from_="pending", to="running",
                   requires=("workflow_step_run:create",),
                   event="workflow_step_run.transitioned"),
    TransitionSpec(from_="running", to="completed",
                   requires=("workflow_step_run:update",),
                   event="workflow_step_run.transitioned"),
    TransitionSpec(from_="running", to="failed",
                   requires=("workflow_step_run:update",),
                   event="workflow_step_run.transitioned"),
    TransitionSpec(from_="pending", to="skipped",
                   requires=("workflow_step_run:update",),
                   event="workflow_step_run.transitioned"),
    TransitionSpec(from_="running", to="skipped",
                   requires=("workflow_step_run:update",),
                   event="workflow_step_run.transitioned"),
)


STATE_MACHINES: Final[dict[str, tuple[TransitionSpec, ...]]] = {
    "work_order": WORK_ORDER_TRANSITIONS,
    "workflow": WORKFLOW_TRANSITIONS,
    "workflow_execution": WORKFLOW_EXECUTION_TRANSITIONS,
    "workflow_step_run": WORKFLOW_STEP_RUN_TRANSITIONS,
}


def describe_transition(
    machine: str, from_state: str, to_state: str
) -> dict:
    """Return {'ok': True, 'spec': {...}} or {'ok': False, 'reason': '...'}."""
    if machine not in STATE_MACHINES:
        return {"ok": False, "reason": "unknown_machine"}
    if from_state == to_state:
        return {"ok": False, "reason": "illegal_transition"}
    saw_from = False
    for t in STATE_MACHINES[machine]:
        if t.from_ == from_state:
            saw_from = True
            if t.to == to_state:
                return {"ok": True, "spec": t.to_dict()}
    return {
        "ok": False,
        "reason": "illegal_transition" if saw_from else "unknown_from",
    }


def is_legal_transition(machine: str, from_state: str, to_state: str) -> bool:
    return describe_transition(machine, from_state, to_state).get("ok", False)
