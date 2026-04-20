import { describe, it, expect } from "vitest";

import {
  STATE_MACHINES,
  describeTransition,
  isLegalTransition,
  legalTransitionsFrom,
  type StateMachineKey,
  type TransitionSpec,
} from "../../packages/contracts/wo-wf/state_machines";

// ── work_order transitions ────────────────────────────────────────────

describe("Loop 6 Phase 6.1 — work_order transition validator", () => {
  it("pending → processing is legal; requires work_order:submit", () => {
    const r = describeTransition("work_order", "pending", "processing");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.spec.requires).toContain("work_order:submit");
      expect(r.spec.event).toBe("work_order.transitioned");
    }
  });

  it("pending → completed is illegal (must go through processing)", () => {
    const r = describeTransition("work_order", "pending", "completed");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("illegal_transition");
  });

  it("cancelled → processing is illegal — cancelled is terminal-hard", () => {
    const r = describeTransition("work_order", "cancelled", "processing");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("unknown_from");
  });

  for (const terminal of ["completed", "done", "failed"] as const) {
    it(`${terminal} → processing is legal via reopen; requires both execution_cycle:reopen and work_order:update`, () => {
      const r = describeTransition("work_order", terminal, "processing");
      expect(r.ok).toBe(true);
      if (r.ok) {
        expect(r.spec.requires).toEqual([
          "execution_cycle:reopen",
          "work_order:update",
        ]);
        expect(r.spec.requiresCycle).toBe(true);
        expect(r.spec.event).toBe("work_order.reopened");
      }
    });
  }

  it("blocked → processing uses unblocked audit event (distinct from generic)", () => {
    const r = describeTransition("work_order", "blocked", "processing");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.spec.event).toBe("work_order.unblocked");
  });

  it("processing → blocked has TWO valid specs: regular block + watchdog_expired", () => {
    // Both specs legitimately have from=processing, to=blocked; the
    // helper (Phase 6.2) picks the correct one based on the trigger.
    // The validator returns the FIRST match — the regular block — by
    // design. The watchdog spec is picked by `STATE_MACHINES` list
    // traversal in the Phase 6.2 helper.
    const r = describeTransition("work_order", "processing", "blocked");
    expect(r.ok).toBe(true);
    if (r.ok) {
      // First match = regular block with work_order.blocked event
      expect(r.spec.event).toBe("work_order.blocked");
    }
  });

  it("same-state transition is rejected as illegal (avoids noop audit spam)", () => {
    const r = describeTransition("work_order", "processing", "processing");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("illegal_transition");
  });

  it("unknown from-state returns unknown_from", () => {
    const r = describeTransition(
      "work_order",
      "frobnicated" as never,
      "processing"
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("unknown_from");
  });

  it("cancel paths all require work_order:cancel and emit work_order.cancelled", () => {
    for (const from of [
      "pending",
      "processing",
      "blocked",
      "awaiting_operator",
      "deferred",
    ] as const) {
      const r = describeTransition("work_order", from, "cancelled");
      expect(r.ok, `${from} → cancelled should be legal`).toBe(true);
      if (r.ok) {
        expect(r.spec.requires).toEqual(["work_order:cancel"]);
        expect(r.spec.event).toBe("work_order.cancelled");
      }
    }
  });

  it("legalTransitionsFrom enumerates the outgoing set deterministically", () => {
    expect(legalTransitionsFrom("work_order", "pending")).toEqual([
      "cancelled",
      "deferred",
      "processing",
    ]);
    expect(legalTransitionsFrom("work_order", "cancelled")).toEqual([]);
  });
});

// ── workflow transitions ──────────────────────────────────────────────

describe("Loop 6 Phase 6.1 — workflow transition validator", () => {
  it("active ↔ paused uses workflow.paused / workflow.resumed events", () => {
    const pause = describeTransition("workflow", "active", "paused");
    expect(pause.ok).toBe(true);
    if (pause.ok) expect(pause.spec.event).toBe("workflow.paused");
    const resume = describeTransition("workflow", "paused", "active");
    expect(resume.ok).toBe(true);
    if (resume.ok) expect(resume.spec.event).toBe("workflow.resumed");
  });

  it("archived is terminal — no outgoing transitions", () => {
    expect(legalTransitionsFrom("workflow", "archived")).toEqual([]);
  });

  it("both active and paused can archive", () => {
    expect(isLegalTransition("workflow", "active", "archived")).toBe(true);
    expect(isLegalTransition("workflow", "paused", "archived")).toBe(true);
  });
});

// ── workflow_execution transitions ────────────────────────────────────

describe("Loop 6 Phase 6.1 — workflow_execution transition validator", () => {
  it("failed → running reopen requires both execution_cycle:reopen and workflow_execution:update", () => {
    const r = describeTransition("workflow_execution", "failed", "running");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.spec.requires).toEqual([
        "execution_cycle:reopen",
        "workflow_execution:update",
      ]);
      expect(r.spec.requiresCycle).toBe(true);
    }
  });

  it("cancel from pending or running requires workflow:cancel", () => {
    for (const from of ["pending", "running"] as const) {
      const r = describeTransition("workflow_execution", from, "cancelled");
      expect(r.ok).toBe(true);
      if (r.ok) {
        expect(r.spec.requires).toEqual(["workflow:cancel"]);
        expect(r.spec.event).toBe("workflow_execution.cancelled");
      }
    }
  });

  it("completed is terminal (no reopen path)", () => {
    expect(legalTransitionsFrom("workflow_execution", "completed")).toEqual([]);
  });
});

// ── workflow_step_run transitions ─────────────────────────────────────

describe("Loop 6 Phase 6.1 — workflow_step_run transition validator", () => {
  it("pending → running requires workflow_step_run:create", () => {
    const r = describeTransition(
      "workflow_step_run",
      "pending",
      "running"
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.spec.requires).toEqual(["workflow_step_run:create"]);
  });

  it("running → completed / failed / skipped all use update permission", () => {
    for (const to of ["completed", "failed", "skipped"] as const) {
      const r = describeTransition("workflow_step_run", "running", to);
      expect(r.ok).toBe(true);
      if (r.ok) expect(r.spec.requires).toEqual(["workflow_step_run:update"]);
    }
  });

  it("completed / failed / skipped are terminal (no outgoing)", () => {
    for (const terminal of ["completed", "failed", "skipped"] as const) {
      expect(legalTransitionsFrom("workflow_step_run", terminal)).toEqual([]);
    }
  });
});

// ── structural invariants across all machines ─────────────────────────

describe("Loop 6 Phase 6.1 — state-machine structural invariants", () => {
  it("every transition's requires list is non-empty (no bypass gates)", () => {
    for (const [name, table] of Object.entries(STATE_MACHINES) as [
      StateMachineKey,
      readonly TransitionSpec[]
    ][]) {
      for (const t of table) {
        expect(
          t.requires.length,
          `${name} ${t.from} → ${t.to} has empty requires list`
        ).toBeGreaterThan(0);
      }
    }
  });

  it("every transition emits a Loop 6 Phase 1 audit event", () => {
    const allowed = new Set([
      "work_order.transitioned",
      "work_order.reopened",
      "work_order.cancelled",
      "work_order.blocked",
      "work_order.unblocked",
      "work_order.watchdog_expired",
      "workflow.transitioned",
      "workflow.paused",
      "workflow.resumed",
      "workflow_execution.transitioned",
      "workflow_execution.cancelled",
      "workflow_step_run.transitioned",
    ]);
    for (const [name, table] of Object.entries(STATE_MACHINES) as [
      StateMachineKey,
      readonly TransitionSpec[]
    ][]) {
      for (const t of table) {
        expect(
          allowed.has(t.event),
          `${name} ${t.from} → ${t.to} emits non-Loop-6 event '${t.event}'`
        ).toBe(true);
      }
    }
  });

  it("requiresCycle transitions always pair with a reopen-class event or watchdog_expired", () => {
    for (const [name, table] of Object.entries(STATE_MACHINES) as [
      StateMachineKey,
      readonly TransitionSpec[]
    ][]) {
      for (const t of table) {
        if (!t.requiresCycle) continue;
        const validEvents = [
          "work_order.reopened",
          "work_order.watchdog_expired",
          "workflow_execution.transitioned", // reopen on wf-exec uses generic event + requires cycle
        ];
        expect(
          validEvents,
          `${name} ${t.from} → ${t.to} has requiresCycle=true but unexpected event '${t.event}'`
        ).toContain(t.event);
      }
    }
  });
});
