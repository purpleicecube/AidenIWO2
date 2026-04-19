/**
 * Manager Reporting Service — Truthful Operational Summaries
 *
 * Derives snapshot metrics (what is true now) and lifecycle metrics
 * (what happened during a time window) from existing work orders,
 * execution logs, and archive/kill metadata.
 *
 * Does NOT replace dashboard stats. Separate reporting path for
 * time-bounded manager questions.
 */

import { storage } from "./storage";
import type { WorkOrder, ExecutionLog } from "@shared/schema";

// ─── Types ───────────────────────────────────────────────────────────────────

/** Default operator timezone for "today" reporting */
export const REPORTING_TIMEZONE = "America/Los_Angeles";

export type ReportWindow = "today" | "last_24h" | "custom";

export interface ReportTimeRange {
  window: ReportWindow;
  start: Date;
  end: Date;
  timezone: string;
}

export interface SnapshotMetrics {
  pendingNow: number;
  processingNow: number;
  blockedNow: number;
  awaitingOperatorNow: number;
  activeNow: number; // pending + processing
  archivedTotal: number;
}

export interface LifecycleMetrics {
  createdDuringWindow: number;
  completedDuringWindow: number;
  blockedDuringWindow: number;
  failedDuringWindow: number;
  killedDuringWindow: number;
  reopenedDuringWindow: number;
}

export interface ReasonSummary {
  reason: string;
  count: number;
}

export interface ManagerReport {
  generatedAt: string;
  timeRange: ReportTimeRange;
  snapshot: SnapshotMetrics;
  lifecycle: LifecycleMetrics;
  blockedReasons: ReasonSummary[];
  failedReasons: ReasonSummary[];
  killedReasons: ReasonSummary[];
}

export interface ReportingGap {
  questionType: string;
  requestedWindow: string;
  missingEvidenceType: string;
  timestamp: string;
  suggestedFollowUp: string;
}

// ─── Time Window ─────────────────────────────────────────────────────────────

/**
 * Compute start/end for a report window.
 * "today" uses REPORTING_TIMEZONE to find midnight-to-now in local time.
 */
export function resolveTimeRange(
  window: ReportWindow,
  timezone: string = REPORTING_TIMEZONE,
  customStart?: string,
  customEnd?: string,
): ReportTimeRange {
  const now = new Date();

  if (window === "last_24h") {
    return {
      window,
      start: new Date(now.getTime() - 24 * 60 * 60 * 1000),
      end: now,
      timezone,
    };
  }

  if (window === "custom" && customStart) {
    return {
      window,
      start: new Date(customStart),
      end: customEnd ? new Date(customEnd) : now,
      timezone,
    };
  }

  // "today" — midnight in the operator's timezone to now
  const todayStr = now.toLocaleDateString("en-US", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" });
  const [month, day, year] = todayStr.split("/");
  // Anchor the calendar date at midnight UTC so the result is independent
  // of the host's local TZ (prior bug: `new Date("YYYY-MM-DDT00:00:00")`
  // without a TZ designator parsed in the system TZ, producing wrong
  // results on any non-UTC host).
  const midnightAsUtc = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), 0, 0, 0));
  // offsetMs > 0 when `timezone` is behind UTC; shift UTC-midnight forward
  // to land on the true local-midnight wall-clock in UTC.
  const offsetMs = getTimezoneOffsetMs(timezone, now);
  const startUtc = new Date(midnightAsUtc.getTime() + offsetMs);

  return {
    window: "today",
    start: startUtc,
    end: now,
    timezone,
  };
}

/** Approximate timezone offset in ms (positive = behind UTC) */
function getTimezoneOffsetMs(tz: string, date: Date): number {
  const utcStr = date.toLocaleString("en-US", { timeZone: "UTC" });
  const tzStr = date.toLocaleString("en-US", { timeZone: tz });
  return new Date(utcStr).getTime() - new Date(tzStr).getTime();
}

// ─── Snapshot Metrics ────────────────────────────────────────────────────────

export function computeSnapshot(orders: WorkOrder[]): SnapshotMetrics {
  const active = orders.filter(o => !o.isArchived);
  let pending = 0, processing = 0, blocked = 0, awaitingOperator = 0;
  for (const o of active) {
    if (o.status === "pending") pending++;
    else if (o.status === "processing") processing++;
    else if (o.status === "blocked") blocked++;
    else if (o.status === "awaiting_operator") awaitingOperator++;
  }
  return {
    pendingNow: pending,
    processingNow: processing,
    blockedNow: blocked,
    awaitingOperatorNow: awaitingOperator,
    activeNow: pending + processing,
    archivedTotal: orders.filter(o => o.isArchived).length,
  };
}

// ─── Lifecycle Metrics ───────────────────────────────────────────────────────

export function computeLifecycle(orders: WorkOrder[], logs: ExecutionLog[], range: ReportTimeRange): LifecycleMetrics {
  const inWindow = (d: Date | string | null) => {
    if (!d) return false;
    const t = new Date(d).getTime();
    return t >= range.start.getTime() && t <= range.end.getTime();
  };

  // Created during window — use createdAt on work orders
  const createdDuringWindow = orders.filter(o => inWindow(o.createdAt)).length;

  // For completed/blocked/failed/killed/reopened — use execution log events as primary evidence
  let completedDuringWindow = 0;
  let blockedDuringWindow = 0;
  let failedDuringWindow = 0;
  let killedDuringWindow = 0;
  let reopenedDuringWindow = 0;

  // Track unique WOs per event type to avoid double-counting
  const completedWos = new Set<string>();
  const blockedWos = new Set<string>();
  const failedWos = new Set<string>();
  const killedWos = new Set<string>();
  const reopenedWos = new Set<string>();

  for (const log of logs) {
    if (!inWindow(log.createdAt)) continue;
    const action = (log.action || "").toLowerCase();
    const woId = log.workOrderId;

    if ((action.includes("completed") || action.includes("resolution")) && !action.includes("revision")) {
      if (!completedWos.has(woId)) { completedWos.add(woId); completedDuringWindow++; }
    }
    if (action.includes("blocked") || action.includes("bdm") || action.includes("policy block")) {
      if (!blockedWos.has(woId)) { blockedWos.add(woId); blockedDuringWindow++; }
    }
    if (action.includes("failed") || action.includes("watchdog") || action.includes("stuck")) {
      if (!failedWos.has(woId)) { failedWos.add(woId); failedDuringWindow++; }
    }
    if (action.includes("killed") || action.includes("kill")) {
      if (!killedWos.has(woId)) { killedWos.add(woId); killedDuringWindow++; }
    }
    if (action.includes("reopened") || action.includes("reopen")) {
      if (!reopenedWos.has(woId)) { reopenedWos.add(woId); reopenedDuringWindow++; }
    }
  }

  // Fallback: also count WOs that transitioned to terminal states during window
  // (catches cases where execution logs were sparse)
  for (const o of orders) {
    if (o.status === "completed" && inWindow(o.updatedAt) && !completedWos.has(o.id)) {
      completedDuringWindow++;
    }
    if (o.status === "failed" && inWindow(o.updatedAt) && !failedWos.has(o.id)) {
      failedDuringWindow++;
    }
  }

  // Include archived+killed WOs
  for (const o of orders) {
    if (o.isArchived && (o as any).archivedReason?.toLowerCase().includes("kill") && inWindow((o as any).archivedAt)) {
      if (!killedWos.has(o.id)) { killedWos.add(o.id); killedDuringWindow++; }
    }
  }

  return { createdDuringWindow, completedDuringWindow, blockedDuringWindow, failedDuringWindow, killedDuringWindow, reopenedDuringWindow };
}

// ─── Reason Aggregation ──────────────────────────────────────────────────────

export function aggregateReasons(logs: ExecutionLog[], range: ReportTimeRange, eventType: "blocked" | "failed" | "killed"): ReasonSummary[] {
  const inWindow = (d: Date | string | null) => {
    if (!d) return false;
    const t = new Date(d).getTime();
    return t >= range.start.getTime() && t <= range.end.getTime();
  };

  const patterns: Record<string, string[]> = {
    blocked: ["blocked", "bdm", "policy block", "step block"],
    failed: ["failed", "watchdog", "stuck", "error"],
    killed: ["killed", "kill"],
  };

  const reasons = new Map<string, number>();

  for (const log of logs) {
    if (!inWindow(log.createdAt)) continue;
    const action = (log.action || "").toLowerCase();
    const matches = patterns[eventType].some(p => action.includes(p));
    if (!matches) continue;

    // Extract reason from message
    const message = log.message || log.action || "Unknown reason";
    // Normalize: take first sentence or first 120 chars
    const reason = message.split(/[.!]\s/)[0].slice(0, 120);
    reasons.set(reason, (reasons.get(reason) || 0) + 1);
  }

  return [...reasons.entries()]
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);
}

// ─── Main Report Generator ──────────────────────────────────────────────────

export async function generateManagerReport(
  window: ReportWindow = "today",
  customStart?: string,
  customEnd?: string,
): Promise<ManagerReport> {
  const range = resolveTimeRange(window, REPORTING_TIMEZONE, customStart, customEnd);

  // Fetch all data in parallel
  const [allOrders, allLogs] = await Promise.all([
    storage.getWorkOrders(),
    fetchAllExecutionLogs(range),
  ]);

  const snapshot = computeSnapshot(allOrders);
  const lifecycle = computeLifecycle(allOrders, allLogs, range);

  const blockedReasons = aggregateReasons(allLogs, range, "blocked");
  const failedReasons = aggregateReasons(allLogs, range, "failed");
  const killedReasons = aggregateReasons(allLogs, range, "killed");

  return {
    generatedAt: new Date().toISOString(),
    timeRange: range,
    snapshot,
    lifecycle,
    blockedReasons,
    failedReasons,
    killedReasons,
  };
}

/**
 * Fetch execution logs across all WOs within the time range.
 * Uses existing storage methods — iterates WO IDs and collects logs.
 */
async function fetchAllExecutionLogs(range: ReportTimeRange): Promise<ExecutionLog[]> {
  const allOrders = await storage.getWorkOrders();
  // Only query logs for WOs that were active or modified during the window
  const candidateWos = allOrders.filter(o => {
    const created = new Date(o.createdAt).getTime();
    const updated = new Date(o.updatedAt).getTime();
    return created <= range.end.getTime() && updated >= range.start.getTime();
  });

  const allLogs: ExecutionLog[] = [];
  // Batch: max 50 WOs to avoid excessive queries
  for (const wo of candidateWos.slice(0, 50)) {
    try {
      const logs = await storage.getExecutionLogs(wo.id);
      allLogs.push(...logs);
    } catch { /* skip inaccessible WOs */ }
  }
  return allLogs;
}

// ─── Chat Integration Helpers ────────────────────────────────────────────────

/**
 * Detect if a chat message is a manager/reporting question.
 */
export function isManagerQuestion(message: string): boolean {
  const lower = message.toLowerCase();
  const patterns = [
    /how many.*(?:work order|wo|order|task)/,
    /how many.*(?:blocked|failed|killed|completed|processed|active)/,
    /what.*(?:blocked|failed|killed).*today/,
    /(?:daily|today|yesterday).*(?:report|summary|status|count)/,
    /(?:top|common).*(?:failure|block|error|reason)/,
    /what.*(?:currently|right now).*(?:active|pending|processing)/,
    /(?:operational|operations?).*(?:report|summary|status)/,
    /why.*(?:blocked|failed|killed)/,
    /status.*(?:report|summary|overview)/,
  ];
  return patterns.some(p => p.test(lower));
}

/**
 * Format a ManagerReport into a concise text brief for Aiden's chat context.
 */
export function formatReportForChat(report: ManagerReport): string {
  const r = report;
  const lines: string[] = [];

  lines.push(`=== OPERATIONAL REPORT (${r.timeRange.window}, ${r.timeRange.timezone}) ===`);
  lines.push(`Report generated: ${r.generatedAt}`);
  lines.push(`Window: ${r.timeRange.start.toISOString()} → ${r.timeRange.end.toISOString()}`);

  lines.push(`\n--- CURRENT SNAPSHOT (right now) ---`);
  lines.push(`Pending: ${r.snapshot.pendingNow} | Processing: ${r.snapshot.processingNow} | Blocked: ${r.snapshot.blockedNow} | Awaiting Operator: ${r.snapshot.awaitingOperatorNow}`);
  lines.push(`Active (pending+processing): ${r.snapshot.activeNow} | Archived: ${r.snapshot.archivedTotal}`);

  lines.push(`\n--- LIFECYCLE (during window) ---`);
  lines.push(`Created: ${r.lifecycle.createdDuringWindow} | Completed: ${r.lifecycle.completedDuringWindow} | Blocked: ${r.lifecycle.blockedDuringWindow} | Failed: ${r.lifecycle.failedDuringWindow} | Killed: ${r.lifecycle.killedDuringWindow} | Reopened: ${r.lifecycle.reopenedDuringWindow}`);

  if (r.blockedReasons.length > 0) {
    lines.push(`\n--- TOP BLOCKED REASONS ---`);
    r.blockedReasons.forEach(br => lines.push(`  (${br.count}×) ${br.reason}`));
  }

  if (r.failedReasons.length > 0) {
    lines.push(`\n--- TOP FAILED REASONS ---`);
    r.failedReasons.forEach(fr => lines.push(`  (${fr.count}×) ${fr.reason}`));
  }

  if (r.killedReasons.length > 0) {
    lines.push(`\n--- TOP KILLED REASONS ---`);
    r.killedReasons.forEach(kr => lines.push(`  (${kr.count}×) ${kr.reason}`));
  }

  lines.push(`\nIMPORTANT: These counts are evidence-based. Lifecycle counts come from execution-log events, not snapshot status. If you cannot answer a question from this data, say: "I don't have that information at this time."`);

  return lines.join("\n");
}

/**
 * Create a reporting-gap note for questions that couldn't be answered.
 */
export function createReportingGap(
  questionType: string,
  requestedWindow: string,
  missingEvidenceType: string,
): ReportingGap {
  return {
    questionType,
    requestedWindow,
    missingEvidenceType,
    timestamp: new Date().toISOString(),
    suggestedFollowUp: `Add ${missingEvidenceType} tracking to manager-reporting service`,
  };
}
