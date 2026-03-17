/**
 * Manager Reporting — Focused Tests
 *
 * Covers: time windows, snapshot vs lifecycle, event counting,
 * archived/killed WOs, reason aggregation, question detection,
 * report formatting, reporting gaps.
 */

import { describe, it, expect } from "vitest";
import {
  resolveTimeRange,
  computeSnapshot,
  computeLifecycle,
  aggregateReasons,
  isManagerQuestion,
  formatReportForChat,
  createReportingGap,
  REPORTING_TIMEZONE,
  type ReportTimeRange,
  type ManagerReport,
} from "../manager-reporting.js";

// ─── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date("2026-03-15T20:00:00Z");
const TODAY_START = new Date("2026-03-15T07:00:00Z"); // midnight PT = 07:00 UTC

function makeWO(overrides: Record<string, any> = {}) {
  return {
    id: overrides.id || "wo-" + Math.random().toString(36).slice(2, 8),
    title: "Test WO",
    description: "",
    type: "standard",
    priority: "medium",
    status: "completed",
    isArchived: false,
    createdAt: new Date("2026-03-15T10:00:00Z"),
    updatedAt: new Date("2026-03-15T12:00:00Z"),
    ...overrides,
  } as any;
}

function makeLog(overrides: Record<string, any> = {}) {
  return {
    id: "log-" + Math.random().toString(36).slice(2, 8),
    workOrderId: overrides.workOrderId || "wo-001",
    tier: 1,
    action: "Test Action",
    message: "Test message",
    metadata: {},
    createdAt: new Date("2026-03-15T11:00:00Z"),
    ...overrides,
  } as any;
}

// ─── Time Windows ────────────────────────────────────────────────────────────

describe("resolveTimeRange()", () => {
  it("last_24h returns a 24-hour window ending now", () => {
    const range = resolveTimeRange("last_24h");
    const diff = range.end.getTime() - range.start.getTime();
    expect(diff).toBe(24 * 60 * 60 * 1000);
  });

  it("today uses the configured reporting timezone", () => {
    const range = resolveTimeRange("today", REPORTING_TIMEZONE);
    expect(range.timezone).toBe("America/Los_Angeles");
    expect(range.window).toBe("today");
    // Start should be earlier than end
    expect(range.start.getTime()).toBeLessThan(range.end.getTime());
  });

  it("custom accepts explicit start/end", () => {
    const range = resolveTimeRange("custom", "UTC", "2026-03-14T00:00:00Z", "2026-03-15T00:00:00Z");
    expect(range.window).toBe("custom");
    expect(range.start.toISOString()).toBe("2026-03-14T00:00:00.000Z");
    expect(range.end.toISOString()).toBe("2026-03-15T00:00:00.000Z");
  });
});

// ─── Snapshot vs Lifecycle ───────────────────────────────────────────────────

describe("computeSnapshot()", () => {
  it("counts current status correctly", () => {
    const orders = [
      makeWO({ status: "pending" }),
      makeWO({ status: "processing" }),
      makeWO({ status: "processing" }),
      makeWO({ status: "blocked" }),
      makeWO({ status: "completed" }),
      makeWO({ status: "awaiting_operator" }),
      makeWO({ status: "failed", isArchived: true }),
    ];
    const snap = computeSnapshot(orders);
    expect(snap.pendingNow).toBe(1);
    expect(snap.processingNow).toBe(2);
    expect(snap.blockedNow).toBe(1);
    expect(snap.awaitingOperatorNow).toBe(1);
    expect(snap.activeNow).toBe(3); // pending + processing
    expect(snap.archivedTotal).toBe(1);
  });

  it("excludes archived from active counts", () => {
    const orders = [
      makeWO({ status: "pending", isArchived: true }),
      makeWO({ status: "pending", isArchived: false }),
    ];
    const snap = computeSnapshot(orders);
    expect(snap.pendingNow).toBe(1); // only non-archived
    expect(snap.archivedTotal).toBe(1);
  });
});

describe("computeLifecycle()", () => {
  const range: ReportTimeRange = {
    window: "today",
    start: new Date("2026-03-15T07:00:00Z"),
    end: new Date("2026-03-15T20:00:00Z"),
    timezone: "America/Los_Angeles",
  };

  it("counts created WOs during window", () => {
    const orders = [
      makeWO({ createdAt: new Date("2026-03-15T10:00:00Z") }), // in window
      makeWO({ createdAt: new Date("2026-03-14T10:00:00Z") }), // before window
    ];
    const lifecycle = computeLifecycle(orders, [], range);
    expect(lifecycle.createdDuringWindow).toBe(1);
  });

  it("counts blocked events from execution logs", () => {
    const logs = [
      makeLog({ workOrderId: "wo-1", action: "BDM Marker Emitted", createdAt: new Date("2026-03-15T11:00:00Z") }),
      makeLog({ workOrderId: "wo-2", action: "Aiden: Policy Block", createdAt: new Date("2026-03-15T12:00:00Z") }),
      makeLog({ workOrderId: "wo-3", action: "Something else", createdAt: new Date("2026-03-15T13:00:00Z") }),
    ];
    const lifecycle = computeLifecycle([], logs, range);
    expect(lifecycle.blockedDuringWindow).toBe(2);
  });

  it("counts failed events including watchdog kills", () => {
    const logs = [
      makeLog({ workOrderId: "wo-1", action: "Watchdog: Stuck Detection", createdAt: new Date("2026-03-15T11:00:00Z") }),
      makeLog({ workOrderId: "wo-2", action: "PocketFlow failed", createdAt: new Date("2026-03-15T12:00:00Z") }),
    ];
    const lifecycle = computeLifecycle([], logs, range);
    expect(lifecycle.failedDuringWindow).toBe(2);
  });

  it("does not double-count same WO for same event type", () => {
    const logs = [
      makeLog({ workOrderId: "wo-1", action: "BDM Marker Emitted", createdAt: new Date("2026-03-15T11:00:00Z") }),
      makeLog({ workOrderId: "wo-1", action: "Blocked again", createdAt: new Date("2026-03-15T12:00:00Z") }),
    ];
    const lifecycle = computeLifecycle([], logs, range);
    expect(lifecycle.blockedDuringWindow).toBe(1);
  });

  it("includes archived+killed WOs in killed count", () => {
    const orders = [
      makeWO({ id: "wo-k1", status: "failed", isArchived: true, archivedReason: "Killed by operator", archivedAt: new Date("2026-03-15T14:00:00Z") }),
    ];
    const lifecycle = computeLifecycle(orders, [], range);
    expect(lifecycle.killedDuringWindow).toBe(1);
  });
});

// ─── Reason Aggregation ──────────────────────────────────────────────────────

describe("aggregateReasons()", () => {
  const range: ReportTimeRange = {
    window: "today",
    start: new Date("2026-03-15T07:00:00Z"),
    end: new Date("2026-03-15T20:00:00Z"),
    timezone: "America/Los_Angeles",
  };

  it("returns top blocked reasons sorted by count", () => {
    const logs = [
      makeLog({ action: "BDM Marker Emitted", message: "Missing deliverable artifact", createdAt: new Date("2026-03-15T10:00:00Z") }),
      makeLog({ action: "BDM Marker Emitted", message: "Missing deliverable artifact", createdAt: new Date("2026-03-15T11:00:00Z") }),
      makeLog({ action: "Policy Block", message: "Budget exceeded", createdAt: new Date("2026-03-15T12:00:00Z") }),
    ];
    const reasons = aggregateReasons(logs, range, "blocked");
    expect(reasons.length).toBe(2);
    expect(reasons[0].reason).toContain("Missing deliverable");
    expect(reasons[0].count).toBe(2);
  });

  it("returns empty array when no matching events", () => {
    const logs = [
      makeLog({ action: "Completed", message: "All done", createdAt: new Date("2026-03-15T10:00:00Z") }),
    ];
    const reasons = aggregateReasons(logs, range, "killed");
    expect(reasons).toEqual([]);
  });
});

// ─── Manager Question Detection ──────────────────────────────────────────────

describe("isManagerQuestion()", () => {
  it("detects 'how many work orders today'", () => {
    expect(isManagerQuestion("How many work orders were processed today?")).toBe(true);
  });

  it("detects 'why were they blocked'", () => {
    expect(isManagerQuestion("Why were work orders blocked today?")).toBe(true);
  });

  it("detects 'what is currently active'", () => {
    expect(isManagerQuestion("What is currently active right now?")).toBe(true);
  });

  it("detects 'daily status report'", () => {
    expect(isManagerQuestion("Give me a daily status report")).toBe(true);
  });

  it("detects 'top failure causes'", () => {
    expect(isManagerQuestion("What are the top failure causes today?")).toBe(true);
  });

  it("does not match generic chat", () => {
    expect(isManagerQuestion("Hello Aiden")).toBe(false);
  });

  it("does not match work order creation", () => {
    expect(isManagerQuestion("Create a presentation about Klear.ai")).toBe(false);
  });
});

// ─── Report Formatting ──────────────────────────────────────────────────────

describe("formatReportForChat()", () => {
  it("includes snapshot and lifecycle sections", () => {
    const report: ManagerReport = {
      generatedAt: "2026-03-15T20:00:00Z",
      timeRange: { window: "today", start: new Date("2026-03-15T07:00:00Z"), end: new Date("2026-03-15T20:00:00Z"), timezone: "America/Los_Angeles" },
      snapshot: { pendingNow: 1, processingNow: 2, blockedNow: 0, awaitingOperatorNow: 1, activeNow: 3, archivedTotal: 5 },
      lifecycle: { createdDuringWindow: 8, completedDuringWindow: 6, blockedDuringWindow: 1, failedDuringWindow: 1, killedDuringWindow: 0, reopenedDuringWindow: 0 },
      blockedReasons: [{ reason: "Missing artifact", count: 1 }],
      failedReasons: [{ reason: "Watchdog timeout", count: 1 }],
      killedReasons: [],
    };
    const text = formatReportForChat(report);
    expect(text).toContain("CURRENT SNAPSHOT");
    expect(text).toContain("LIFECYCLE");
    expect(text).toContain("Pending: 1");
    expect(text).toContain("Created: 8");
    expect(text).toContain("Missing artifact");
    expect(text).toContain("I don't have that information");
  });
});

// ─── Reporting Gap ───────────────────────────────────────────────────────────

describe("createReportingGap()", () => {
  it("creates a structured gap note", () => {
    const gap = createReportingGap("daily_revenue", "today", "financial_data");
    expect(gap.questionType).toBe("daily_revenue");
    expect(gap.requestedWindow).toBe("today");
    expect(gap.missingEvidenceType).toBe("financial_data");
    expect(gap.timestamp).toBeTruthy();
    expect(gap.suggestedFollowUp).toContain("financial_data");
  });
});
