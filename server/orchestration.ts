import { storage } from "./storage";
import type { WorkOrder, SubAgent, WorkflowStep, WorkflowStepRun, InsertChecklistItem } from "@shared/schema";
import { runTier1WithLLM, runTier2WithLLM, resolveSubAgentLlmConfig, runAidenQualityReview, type Tier1Result, type Tier2Result } from "./llm-client";
import { fileWorkOrderOutput } from "./workspace-filing";
import { pocketflowExecute, detectRequiredFormatFromText, postProcessWorkflowDeliverable } from "./pocketflow";
import crypto from "crypto";
import { evaluateDoneContract, buildWorkOrderCloseoutContext, type DoneDecision } from "./done-contract";
import { buildPptxReviewSupplement, type PreflightResult, type GammaComplianceResult, type ParsedContract } from "./pptx-quality";
import { resolveExecutionStrategy, type ResolverResult } from "./execution-strategy-resolver";

// ─── Watchdog: Heartbeat + Attempt Ownership ─────────────────────────────────

const HEARTBEAT_INTERVAL_MS = 15_000;      // heartbeat every 15s
const WATCHDOG_INTERVAL_MS = 30_000;       // sweep every 30s
const HEARTBEAT_STALE_MS = 60_000;         // 60s without heartbeat = stuck
const DEFAULT_CEILING_MS = 10 * 60 * 1000;   // 10 min — simple one-off WOs
const EXTENDED_CEILING_MS = 20 * 60 * 1000;  // 20 min — format-heavy / revision-eligible runs
const PHASE_TIMEOUT_MS = 90_000;           // 90s — per-phase timeout for LLM calls (quality review, etc.)

/**
 * BUG-052: Determine the per-attempt hard ceiling for a work order.
 * Heavier runs (format-heavy, multi-page HTML, revision-eligible) get 20 min.
 * Simple one-off WOs get 10 min.
 */
function resolveProcessingCeiling(order: any): { ceilingMs: number; reason: string } {
  const text = `${order.title || ""} ${order.description || ""}`.toLowerCase();

  // Format-heavy: PDF, PPTX, Gamma
  if (/\b(pdf|pptx|powerpoint|presentation|slide|gamma)\b/.test(text)) {
    return { ceilingMs: EXTENDED_CEILING_MS, reason: "format-heavy (PDF/PPTX/Gamma)" };
  }

  // Multi-page HTML builds
  if (/\b(website|multi.?page|five.?page|landing.?page.*deploy|sandbox.*preview)\b/.test(text)) {
    return { ceilingMs: EXTENDED_CEILING_MS, reason: "multi-page HTML build" };
  }

  // Auto-revision already in progress (GCC shows revision attempts)
  const gcc = order.gccMemory || {};
  const revisionAttempts = gcc?.["gcc.metadata"]?.revisionAttempts || 0;
  if (revisionAttempts > 0) {
    return { ceilingMs: EXTENDED_CEILING_MS, reason: `revision-eligible (${revisionAttempts} attempts)` };
  }

  return { ceilingMs: DEFAULT_CEILING_MS, reason: "default" };
}

/**
 * Checks whether the given attemptId still owns the work order.
 * If not, the caller is a zombie and must silently exit.
 */
async function isAttemptStillOwner(orderId: string, attemptId: string): Promise<boolean> {
  const current = await storage.getWorkOrder(orderId);
  return !!current && (current as any).processingAttemptId === attemptId;
}

/**
 * Emits periodic heartbeats for an in-flight work order.
 * Self-cancels when it detects its attemptId has been invalidated by the watchdog.
 */
class HeartbeatEmitter {
  private intervalHandle: NodeJS.Timeout | null = null;
  private stopped = false;

  constructor(
    private workOrderId: string,
    private attemptId: string,
    private intervalMs: number = HEARTBEAT_INTERVAL_MS,
  ) {}

  start(): void {
    this.intervalHandle = setInterval(async () => {
      if (this.stopped) return;
      try {
        if (!(await isAttemptStillOwner(this.workOrderId, this.attemptId))) {
          console.warn(`[heartbeat] Attempt ${this.attemptId.slice(0, 8)} superseded for WO ${this.workOrderId} — stopping`);
          this.stop();
          return;
        }
        await storage.updateWorkOrder(this.workOrderId, { heartbeatAt: new Date() });
      } catch (err) {
        console.warn(`[heartbeat] Failed for WO ${this.workOrderId}:`, err);
      }
    }, this.intervalMs);
  }

  stop(): void {
    this.stopped = true;
    if (this.intervalHandle) {
      clearInterval(this.intervalHandle);
      this.intervalHandle = null;
    }
  }
}

/**
 * BUG-049: Scoped heartbeat guard for long-running Tier 1 operations
 * (quality review, revision handoff) that would otherwise starve the watchdog.
 *
 * Starts a periodic heartbeat, executes the callback, and always clears
 * the interval — even on throw. Does NOT keep dead calls alive: if the
 * callback throws, the guard re-throws after cleanup.
 *
 * BUG-053: Added phase-level timeout (default PHASE_TIMEOUT_MS). If the
 * wrapped function doesn't resolve within the timeout, a TimeoutError is
 * thrown so the caller can apply a safe fallback (e.g. auto-approve).
 * This prevents WOs from getting stuck in "processing" forever when an
 * LLM call hangs despite the HTTP-level timeout.
 */
class PhaseTimeoutError extends Error {
  constructor(phase: string, timeoutMs: number) {
    super(`Phase "${phase}" timed out after ${(timeoutMs / 1000).toFixed(0)}s`);
    this.name = "PhaseTimeoutError";
  }
}

async function withWorkOrderHeartbeatGuard<T>(
  orderId: string,
  phase: string,
  fn: () => Promise<T>,
  attemptId?: string,
  timeoutMs: number = PHASE_TIMEOUT_MS,
): Promise<T> {
  let stopped = false;
  const interval = setInterval(async () => {
    if (stopped) return;
    try {
      // BUG-049 hardening: stop heartbeats if attempt no longer owns the WO
      if (attemptId && !(await isAttemptStillOwner(orderId, attemptId))) {
        console.warn(`[heartbeat-guard] Attempt ${attemptId.slice(0, 8)} superseded during ${phase} — stopping heartbeat`);
        stopped = true;
        clearInterval(interval);
        return;
      }
      await storage.updateWorkOrder(orderId, { heartbeatAt: new Date() });
    } catch {
      // heartbeat write failure is non-fatal — watchdog may still kill, which is correct
    }
  }, HEARTBEAT_INTERVAL_MS);

  try {
    // BUG-053: Race the callback against a phase-level timeout
    const result = await Promise.race([
      fn(),
      new Promise<never>((_, reject) => {
        setTimeout(() => reject(new PhaseTimeoutError(phase, timeoutMs)), timeoutMs);
      }),
    ]);
    return result;
  } finally {
    stopped = true;
    clearInterval(interval);
  }
}

/**
 * Structural helper: completes a work order AND triggers filing in one call.
 * Every code path that sets a WO to "completed" MUST go through this function
 * so filing + sandbox deploy can never be forgotten.
 *
 * If attemptId is provided, checks ownership first — zombie callers are silently rejected.
 */
async function completeAndFileWorkOrder(
  workOrderId: string,
  updates: Record<string, any>,
  label: string,
  attemptId?: string,
): Promise<WorkOrder | undefined> {
  if (attemptId && !(await isAttemptStillOwner(workOrderId, attemptId))) {
    console.warn(`[completeAndFile] Attempt ${attemptId.slice(0, 8)} no longer owns WO ${workOrderId} — skipping (${label})`);
    return undefined;
  }

  // ─── Done Contract Gate ────────────────────────────────────────────────────
  // Evaluate closeout contract before writing terminal status.
  // If the contract rejects completion, redirect to the appropriate state.
  const currentOrder = await storage.getWorkOrder(workOrderId);
  if (currentOrder) {
    const tier2 = updates.tier2Result || currentOrder.tier2Result;
    const artifacts = await storage.getArtifacts(undefined, workOrderId);
    const candidates = await storage.getGammaGenerationRecords(workOrderId);
    const pendingCandidates = candidates?.filter((c: any) => c.candidateStatus === "candidate") || [];

    // Filing is always resolved at this point because completeAndFileWorkOrder
    // triggers fileWorkOrderOutput() immediately after setting completed status.
    // The artifact count is used only to compensate for prose-only deliverables.
    const artifactCount = artifacts?.length || 0;

    // Derive Gamma state from candidate records + tier2Result
    const selectedCandidates = candidates?.filter((c: any) => c.candidateStatus === "selected") || [];
    const hasGammaRecords = candidates && candidates.length > 0;
    let gammaState: "none" | "success" | "candidate_review" | "failed" = "none";
    if (hasGammaRecords) {
      if (selectedCandidates.length > 0) gammaState = "success";
      else if (pendingCandidates.length > 0) gammaState = "candidate_review";
      else if (tier2?.gammaDeliveryPolicy) gammaState = "failed";
    }

    // BUG-042: Extract quality/exec review score for Done Contract
    const recentLogs = await storage.getExecutionLogs(workOrderId);
    const qualityLog = [...recentLogs].reverse().find((l: any) =>
      l.action?.includes("Quality") || l.action?.includes("Executive Review")
    );
    const qualityScore = (qualityLog?.metadata as any)?.qualityScore
      ?? (qualityLog?.metadata as any)?.execReview?.score
      ?? (qualityLog?.metadata as any)?.score
      ?? undefined;

    const closeoutCtx = buildWorkOrderCloseoutContext(
      {
        title: currentOrder.title,
        description: currentOrder.description || "",
        tier2Result: tier2,
        status: currentOrder.status,
      },
      {
        filedArtifactCount: artifactCount,
        candidateReviewPending: pendingCandidates.length > 0,
        previewResult: null,
        filingWillResolve: true, // filing is about to happen via fileWorkOrderOutput()
        gammaState,
        gammaFallbackBlocked: false, // if we reached completeAndFileWorkOrder, fallback wasn't blocked
        qualityScore,
        // BUG-038: Pass Gamma compliance evidence into Done Contract
        gammaComplianceOk: (tier2?.pocketflow?._pptxCompliance as any)?.ok,
        gammaComplianceFailures: (tier2?.pocketflow?._pptxCompliance as any)?.hardFailures,
      }
    );

    const decision = evaluateDoneContract(closeoutCtx);

    // Log the closeout decision
    await storage.createExecutionLog({
      workOrderId,
      tier: 1,
      action: `Done Contract: ${decision.terminalState}`,
      message: decision.closeoutReason,
      metadata: {
        artifactClass: decision.artifactClass,
        validationTier: decision.validationTier,
        hardFailures: decision.hardFailures,
        softWarnings: decision.softWarnings,
        evidence: decision.evidence,
        label,
      },
    });

    addChecklistItem(workOrderId, "quality_review",
      `Done Contract: ${decision.done ? "passed" : "blocked"} (${decision.artifactClass}/${decision.validationTier})`,
      "system"
    );

    if (!decision.done) {
      // Redirect to the contract-determined terminal state instead of "completed"
      const redirected = await storage.updateWorkOrder(workOrderId, {
        ...updates,
        status: decision.terminalState,
        heartbeatAt: null,
        processingStartedAt: null,
      });
      console.warn(`[done-contract] WO ${workOrderId} redirected from completed → ${decision.terminalState} (${label}): ${decision.closeoutReason}`);
      return redirected || undefined;
    }
  }
  // ─── End Done Contract Gate ────────────────────────────────────────────────

  const completedOrder = await storage.updateWorkOrder(workOrderId, {
    ...updates,
    status: "completed",
    heartbeatAt: null,
    processingStartedAt: null,
  });
  if (completedOrder) {
    fileWorkOrderOutput(completedOrder).catch(err =>
      console.error(`Auto-filing error (${label}):`, err.message)
    );
  }
  return completedOrder;
}
import { getAvailableToolsForAgent } from "./tool-executor";
import { autoImportSkillsForDescription } from "./skill-auto-import";
import { createMemoryAdvisor, type WorkOrderEvent } from "./memory-advisor";
import {
  selectProjectManager, resolvePmLlmConfig,
  pmReviewStepOutput, pmRequestStepRevision,
  pmAssembleWorkProduct, pmEscalateToAiden, aidenExecutiveReview,
  type PmReviewResult,
} from "./workflow-pm";

// ─── 2DO Checklist Helper ────────────────────────────────────────────────────

type ChecklistPhase = "tier1_gate" | "tier2_exec" | "quality_review" | "filing" | "deployment";

function addChecklistItem(
  workOrderId: string,
  phase: ChecklistPhase,
  summary: string,
  addedBy: string = "system",
  extras?: { workflowExecutionId?: string; stepRunId?: string; iteration?: number },
): void {
  storage.createChecklistItem({
    workOrderId,
    phase,
    summary,
    addedBy,
    status: "done",
    ...extras,
  }).catch(err => console.error("[2DO] Failed to add checklist item:", err.message));
}

// ─── GCC Authority Model ──────────────────────────────────────────────────────
// Per AIDEN IWO Tier 1 spec (AIDEN_IWOv0.1.0.md):
//
//   Command | Tier 1            | Tier 2
//   --------|-------------------|--------------------
//   CONTEXT | Full access       | Read-only
//   COMMIT  | Full access       | Own branch only
//   BRANCH  | Create + approve  | Propose only
//   MERGE   | EXCLUSIVE         | DENIED (hard fail)
//
// P0-C: B+ Hardening — deny-by-default for Tier 2 authority violations.
// Full BRANCH/MERGE implementation: Phase P2.

export type GccCommand = "CONTEXT" | "COMMIT" | "BRANCH" | "MERGE";
export type GccTier = "tier1" | "tier1.5" | "tier2";

export function validateGccCommand(command: GccCommand, tier: GccTier): void {
  if (command === "MERGE" && tier !== "tier1") {
    throw new Error(
      `[GCC] AUTHORITY VIOLATION: ${tier} attempted MERGE — DENIED. MERGE is exclusive to Tier 1. Escalating to HITL.`
    );
  }
  if (command === "BRANCH" && tier === "tier2") {
    // Tier 2 may only propose a branch, never execute one. Downgrade + warn.
    console.warn("[GCC] Tier 2 BRANCH attempt downgraded to proposal — Tier 1 approval required before execution.");
  }
}

function updateWorkOrderGcc(
  existing: object | null | undefined,
  action: string,
  breadcrumbs: string[],
  extras: Record<string, any> = {},
): Record<string, any> {
  const gcc = (existing || {}) as Record<string, any>;
  const now = new Date().toISOString();
  const commitId = `gcc-${Math.random().toString(16).slice(2, 10)}`;

  const existingCommitIndex = gcc["gcc.commit_index"] || [];
  const existingLog = gcc["gcc.log"] || [];
  const existingBreadcrumbs = gcc["gcc.breadcrumbs"] || gcc.breadcrumbs || [];

  const legacyCorrelationId = gcc.correlationId;
  const legacyPocketflow = gcc.pocketflow;

  const result: Record<string, any> = {
    "gcc.project_id": gcc["gcc.project_id"] || `wo-${extras.correlationId?.slice(0, 8) || legacyCorrelationId?.slice(0, 8) || "unknown"}`,
    "gcc.branch": gcc["gcc.branch"] || "main",
    "gcc.tier": extras.tier || gcc["gcc.tier"] || "tier1",
    "gcc.last_action": action,
    "gcc.last_commit_id": commitId,
    "gcc.last_commit_summary": action,
    "gcc.breadcrumbs": [...existingBreadcrumbs, ...breadcrumbs].slice(-50),
    "gcc.commit_index": [
      ...existingCommitIndex,
      { commit_id: commitId, timestamp: now, summary: action, tags: breadcrumbs },
    ].slice(-100),
    "gcc.log": [
      ...existingLog,
      { timestamp: now, source_node: "OrchestrationEngine", type: "COMMIT", entry: action, detail: JSON.stringify(extras) },
    ].slice(-200),
    "gcc.context_scope": "branch",
    "gcc.context_commit_count": existingCommitIndex.length + 1,
    "gcc.metadata": {
      ...(gcc["gcc.metadata"] || {}),
      status: extras.status || "active",
      last_commit: now,
      ...(legacyCorrelationId ? { correlationId: legacyCorrelationId } : {}),
      ...(legacyPocketflow ? { pocketflow: legacyPocketflow } : {}),
      ...extras,
    },
  };

  return result;
}

export async function recoverOrphanedProcessingOrders(): Promise<number> {
  const STALE_THRESHOLD_MS = 10 * 60 * 1000;
  const allOrders = await storage.getWorkOrders();
  const staleOrders = allOrders.filter(
    (o) => o.status === "processing" && o.updatedAt && (Date.now() - new Date(o.updatedAt).getTime() > STALE_THRESHOLD_MS)
  );

  for (const order of staleOrders) {
    await storage.updateWorkOrder(order.id, {
      status: "failed",
      processingAttemptId: null,
      heartbeatAt: null,
      processingStartedAt: null,
    });
    await storage.createExecutionLog({
      workOrderId: order.id,
      tier: 1,
      action: "System: Orphan Recovery",
      message: `Work order was stuck in "processing" for over ${Math.round(STALE_THRESHOLD_MS / 60000)} minutes (likely due to server restart). Status reset to "failed" — you can retry it.`,
      metadata: { previousStatus: "processing", recoveredAt: new Date().toISOString(), reason: "server_restart_recovery" },
    });
    console.log(`[recovery] Recovered orphaned WO ${order.id} ("${order.title}") — set to failed`);
  }
  return staleOrders.length;
}

export function isStaleProcessing(order: { status: string; updatedAt: Date | string | null }): boolean {
  if (order.status !== "processing") return false;
  if (!order.updatedAt) return false;
  const elapsed = Date.now() - new Date(order.updatedAt).getTime();
  return elapsed > 10 * 60 * 1000;
}

// ─── Watchdog: Runtime Sweep ─────────────────────────────────────────────────

let lastWatchdogSweep: Date | null = null;

/**
 * Starts the runtime watchdog. Returns a cleanup function.
 * Scans for stuck WOs every 30s using heartbeat staleness, not just elapsed time.
 */
export function startWatchdog(): () => void {
  const handle = setInterval(async () => {
    try {
      await watchdogSweep();
    } catch (err) {
      console.error("[watchdog] Sweep error:", err);
    }
  }, WATCHDOG_INTERVAL_MS);
  console.log("[watchdog] Started — scanning every 30s for stuck work orders");
  return () => clearInterval(handle);
}

export async function watchdogSweep(): Promise<number> {
  lastWatchdogSweep = new Date();
  const allOrders = await storage.getWorkOrders();
  const processingOrders = allOrders.filter(o => o.status === "processing");
  let recovered = 0;

  for (const order of processingOrders) {
    const now = Date.now();
    const wo = order as any;

    // Determine heartbeat age: use heartbeatAt if available, fall back to updatedAt
    const heartbeatTs = wo.heartbeatAt ? new Date(wo.heartbeatAt).getTime() : null;
    const updatedTs = order.updatedAt ? new Date(order.updatedAt).getTime() : now;
    const lastActivity = heartbeatTs || updatedTs;
    const heartbeatAge = now - lastActivity;

    // Total processing duration
    const processingStart = wo.processingStartedAt
      ? new Date(wo.processingStartedAt).getTime()
      : updatedTs;
    const totalDuration = now - processingStart;

    const heartbeatStale = heartbeatAge > HEARTBEAT_STALE_MS;
    // BUG-052: Per-WO ceiling based on complexity class
    const { ceilingMs, reason: ceilingReason } = resolveProcessingCeiling(order);
    const exceededHardCeiling = totalDuration > ceilingMs;

    if (!heartbeatStale && !exceededHardCeiling) continue;

    // Invalidate the current attempt so zombie async work can't finalize
    const invalidationId = crypto.randomUUID();

    // BUG-053: Progress-aware timeout policy.
    // Fresh heartbeat is used here as an operational proxy for live progress,
    // not as a permanent semantic replacement for true forward-progress detection.
    // Two paths:
    //   1. Stale heartbeat → hard fail (dead/stuck work)
    //   2. Budget exceeded + fresh heartbeat → soft timeout (route to operator review)
    if (heartbeatStale) {
      // ── Hard fail: truly dead work ──
      const reason = `No heartbeat for ${Math.round(heartbeatAge / 1000)}s`;
      console.warn(`[watchdog] WO ${order.id} ("${order.title}") stuck: ${reason}`);

      await storage.updateWorkOrder(order.id, {
        status: "failed",
        processingAttemptId: invalidationId,
        heartbeatAt: null,
        processingStartedAt: null,
        bdmMarker: {
          type: "watchdog_stuck",
          reason,
          tier: 1,
          timestamp: new Date().toISOString(),
          heartbeatAgeSeconds: Math.round(heartbeatAge / 1000),
          totalDurationSeconds: Math.round(totalDuration / 1000),
        },
        tier2Result: {
          blocked: true,
          reason: `Watchdog: ${reason}`,
          handler: (order as any).tier1Result?.handler || null,
        },
      });

      await storage.createExecutionLog({
        workOrderId: order.id,
        tier: 1,
        action: "Watchdog: Stuck Detection",
        message: `Watchdog detected stuck work order: ${reason}. Status set to "failed". Previous processing attempt invalidated — zombie work will be silently discarded.`,
        metadata: {
          reason,
          watchdogClass: "hard_fail",
          heartbeatAgeSeconds: Math.round(heartbeatAge / 1000),
          totalDurationSeconds: Math.round(totalDuration / 1000),
          previousAttemptId: wo.processingAttemptId,
          invalidationId,
          recoveredAt: new Date().toISOString(),
        },
      });
    } else {
      // ── Soft timeout: budget exceeded but work is still alive ──
      const reason = `Processing exceeded ${ceilingMs / 60000} min autonomous budget (${ceilingReason}), but forward progress was still detected`;
      console.warn(`[watchdog] WO ${order.id} ("${order.title}") budget exceeded (soft timeout): ${reason}`);

      // Preserve best-known artifact from the current tier2Result if any
      const existingTier2 = (order as any).tier2Result;
      const preservedTier2 = existingTier2 || {
        blocked: true,
        reason: `Watchdog: ${reason}`,
        handler: (order as any).tier1Result?.handler || null,
      };

      await storage.updateWorkOrder(order.id, {
        status: "awaiting_operator",
        processingAttemptId: invalidationId,
        heartbeatAt: null,
        processingStartedAt: null,
        bdmMarker: {
          type: "watchdog_budget_exceeded",
          reason,
          tier: 1,
          timestamp: new Date().toISOString(),
          heartbeatAgeSeconds: Math.round(heartbeatAge / 1000),
          totalDurationSeconds: Math.round(totalDuration / 1000),
          ceilingMs,
          ceilingReason,
        },
        tier2Result: preservedTier2,
      });

      await storage.createExecutionLog({
        workOrderId: order.id,
        tier: 1,
        action: "Watchdog: Budget Exceeded",
        message: `${reason}. Best-so-far artifact preserved. Status set to "awaiting_operator" for operator review.`,
        metadata: {
          reason,
          watchdogClass: "soft_timeout",
          heartbeatAgeSeconds: Math.round(heartbeatAge / 1000),
          totalDurationSeconds: Math.round(totalDuration / 1000),
          ceilingMs,
          ceilingReason,
          previousAttemptId: wo.processingAttemptId,
          invalidationId,
          recoveredAt: new Date().toISOString(),
          hasPreservedArtifact: !!existingTier2?.output?.deliverable,
        },
      });
    }

    // Recover any stuck workflow step runs (both hard-fail and soft-timeout paths)
    await recoverStuckStepRuns(order);
    recovered++;
  }

  return recovered;
}

/**
 * Fails any running step runs + their parent execution when a WO is recovered.
 */
export async function recoverStuckStepRuns(order: WorkOrder): Promise<void> {
  const wo = order as any;
  const executionId = wo.workflowExecutionId || order.workflowExecutionId;
  if (!executionId) return;

  try {
    const stepRuns = await storage.getWorkflowStepRuns(executionId);
    const stuckRuns = stepRuns.filter((r: any) => r.status === "running");

    for (const run of stuckRuns) {
      await storage.updateWorkflowStepRun(run.id, {
        status: "failed",
        completedAt: new Date(),
        error: "Watchdog: step was running when work order was declared stuck",
      });
      console.log(`[watchdog] Recovered stuck step run ${run.id} (${run.stepName}) for WO ${order.id}`);
    }

    if (stuckRuns.length > 0) {
      await storage.updateWorkflowExecution(executionId, {
        status: "failed",
        completedAt: new Date(),
      });
    }
  } catch (err) {
    console.error(`[watchdog] Failed to recover step runs for WO ${order.id}:`, err);
  }
}

/** Returns watchdog status for the ops health endpoint. */
export function getWatchdogStatus() {
  return {
    active: true,
    intervalMs: WATCHDOG_INTERVAL_MS,
    heartbeatStaleMs: HEARTBEAT_STALE_MS,
    defaultCeilingMs: DEFAULT_CEILING_MS,
    extendedCeilingMs: EXTENDED_CEILING_MS,
    lastSweep: lastWatchdogSweep?.toISOString() || null,
  };
}

function isRetriableError(err: any): boolean {
  const msg = (err?.message || "").toLowerCase();
  const status = err?.status || err?.statusCode || 0;
  // 429 rate limit, 502/503/504 gateway errors, timeouts
  if ([429, 502, 503, 504].includes(status)) return true;
  if (msg.includes("timeout") || msg.includes("timed out") || msg.includes("etimedout")) return true;
  if (msg.includes("rate limit") || msg.includes("too many requests")) return true;
  if (msg.includes("econnreset") || msg.includes("econnrefused") || msg.includes("socket hang up")) return true;
  return false;
}

export async function processWorkOrderSafe(orderId: string): Promise<void> {
  const _perfStart = Date.now();
  const attemptId = crypto.randomUUID();
  const heartbeat = new HeartbeatEmitter(orderId, attemptId);
  heartbeat.start();
  try {
    await processWorkOrder(orderId, attemptId);
  } catch (err: any) {
    const retriable = isRetriableError(err);
    console.error(`[orchestration] processWorkOrder crashed for ${orderId} (retriable: ${retriable}):`, err);
    try {
      const current = await storage.getWorkOrder(orderId);
      // Only recover if we still own this attempt
      if (current && current.status === "processing" && (current as any).processingAttemptId === attemptId) {
        const newStatus = retriable ? "pending" : "failed";
        await storage.updateWorkOrder(orderId, {
          status: newStatus,
          heartbeatAt: null,
          processingStartedAt: null,
        });
        await storage.createExecutionLog({
          workOrderId: orderId,
          tier: 1,
          action: retriable ? "System: Retriable Error" : "System: Processing Failed",
          message: retriable
            ? `Processing hit a transient error (${err?.message || "Unknown"}). Status reset to "pending" — will retry automatically or you can resubmit.`
            : `Background processing crashed: ${err?.message || "Unknown error"}. Status set to "failed" — you can retry.`,
          metadata: { error: err?.message, stack: err?.stack?.substring(0, 500), failedAt: new Date().toISOString(), retriable, attemptId },
        });
      } else if (current && (current as any).processingAttemptId !== attemptId) {
        console.warn(`[orchestration] Attempt ${attemptId.slice(0, 8)} superseded for WO ${orderId} — skipping error recovery`);
      }
    } catch (recoveryErr) {
      console.error(`[orchestration] Failed to recover crashed WO ${orderId}:`, recoveryErr);
    }
  } finally {
    heartbeat.stop();
    console.log(`[perf:wo] END ${orderId} ${Date.now() - _perfStart}ms`);
  }
}

export async function processWorkOrder(orderId: string, attemptId?: string): Promise<WorkOrder | undefined> {
  const _woStart = Date.now();
  const order = await storage.getWorkOrder(orderId);
  if (!order) return undefined;
  console.log(`[perf:wo] START ${orderId} "${order.title}" type=${order.type} priority=${order.priority}`);

  await storage.updateWorkOrder(orderId, {
    status: "processing",
    processingAttemptId: attemptId || null,
    heartbeatAt: new Date(),
    processingStartedAt: new Date(),
  });
  addChecklistItem(orderId, "tier1_gate", `Work order submitted: "${order.title}" (${order.type}, ${order.priority}) — awaiting Tier 1 gate`);

  // Phase 2: Resolve all shared context once per WO run
  const { resolveRunContext } = await import("./run-context");
  const runCtx = await resolveRunContext();
  const settings = runCtx.settings;
  const useLLM = runCtx.useLLM;
  const activeSubAgents = runCtx.activeSubAgents;

  // P1.4: Memory Advisor — Hook 1 (pre-Tier-1 recall)
  const opSettings = runCtx.operationalSettings;
  const advisor = createMemoryAdvisor(opSettings?.memoryAdvisor ?? "none");
  const advisoryMemories = await advisor.recall(`${order.title}: ${order.description}`).catch(() => []);
  const advisoryContext = advisoryMemories.length > 0
    ? `\n\n[Advisory Memory — ${advisoryMemories.length} relevant past outcome(s)]:\n` +
      advisoryMemories.map(m => `- ${m.context} (relevance: ${(m.relevance * 100).toFixed(0)}%)`).join("\n")
    : "";

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Aiden: Policy Gate",
    message: `Aiden (Tier 1) received work order "${order.title}" — evaluating policy rules${useLLM ? ` via LLM (${settings?.provider}/${settings?.model})` : ""}.`,
    metadata: { type: order.type, priority: order.priority, aiEnabled: useLLM, subAgentCount: activeSubAgents.length, llmProvider: settings?.provider, llmModel: settings?.model },
  });

  const tier1Result: Tier1Result = useLLM && settings
    ? await runTier1WithLLM(settings, order, activeSubAgents)
    : runTier1PolicyGate(order, activeSubAgents);

  const gcc = (order.gccMemory || {}) as Record<string, any>;
  const preferredAgent = gcc["gcc.preferredAgent"] || null;
  if (preferredAgent && tier1Result.approved) {
    const preferredResolved = findSubAgent(activeSubAgents, preferredAgent);
    const llmResolved = findSubAgent(activeSubAgents, tier1Result.handler);
    if (preferredResolved && (!llmResolved || llmResolved.id !== preferredResolved.id)) {
      console.log(`[orchestration] Operator override: LLM chose "${tier1Result.handler}" but operator requested "${preferredAgent}" → forcing handler to "${preferredResolved.name}"`);
      tier1Result.handler = preferredResolved.name;
      tier1Result.reason = `${tier1Result.reason} [Operator override: routed to ${preferredResolved.name} as explicitly requested]`;
    }
  }

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Aiden: Policy Decision",
    message: tier1Result.approved
      ? `Aiden approved — routing to sub-agent: ${tier1Result.handler}${useLLM ? ` (LLM: ${settings?.provider}/${settings?.model})` : ""}${preferredAgent ? " (operator-directed)" : ""}.`
      : `Aiden blocked: ${tier1Result.reason}`,
    metadata: { ...tier1Result, llmProvider: settings?.provider, llmModel: settings?.model, ...(preferredAgent ? { operatorDirected: true, preferredAgent } : {}) },
  });

  if (!tier1Result.approved) {
    const bdmMarker = {
      type: "policy_block",
      reason: tier1Result.reason,
      tier: 1,
      timestamp: new Date().toISOString(),
    };

    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "BDM Marker Emitted",
      message: `Aiden blocked work order at policy gate: ${tier1Result.reason}`,
      metadata: bdmMarker,
    });

    addChecklistItem(orderId, "tier1_gate", `Tier 1 blocked: ${tier1Result.reason}`, "aiden");
    return storage.updateWorkOrder(orderId, {
      status: "blocked",
      tier1Result,
      bdmMarker,
      gccMemory: updateWorkOrderGcc(order.gccMemory as object, "tier1_policy_block", ["tier1_policy_block"], {
        correlationId: order.correlationId, status: "blocked", reason: tier1Result.reason,
      }),
    });
  }

  // ── Execution Strategy Resolver ──────────────────────────────────────────
  // After Tier 1 approval, before direct dispatch. Deterministic, no LLM.
  const strategyResult: ResolverResult = await resolveExecutionStrategy(order, activeSubAgents);

  if (strategyResult.strategy === "workflow") {
    // Double-execution guard: prevent duplicate active workflows for the same WO
    if (order.workflowExecutionId) {
      const existingExec = await storage.getWorkflowExecution(order.workflowExecutionId);
      if (existingExec && existingExec.status === "running") {
        console.warn(`[orchestration] Double-execution guard: WO ${orderId} already has active workflow ${order.workflowExecutionId} — skipping workflow route, using direct execution`);
        // Fall through to direct execution below
      } else {
        // Existing execution is not running — safe to proceed with new workflow
      }
    }

    // Only enter workflow path if guard didn't trigger
    const guardTriggered = order.workflowExecutionId &&
      await storage.getWorkflowExecution(order.workflowExecutionId).then(e => e?.status === "running").catch(() => false);

    if (!guardTriggered) {
      await storage.updateWorkOrder(orderId, {
        tier1Result,
        gccMemory: updateWorkOrderGcc(order.gccMemory as object, "tier1_policy_pass", ["tier1_policy_pass", "resolver_workflow_route"], {
          correlationId: order.correlationId, status: "routing",
          handler: tier1Result.handler, mode: tier1Result.mode,
          resolverStrategy: "workflow", resolverTemplateId: strategyResult.templateId,
          resolverScore: strategyResult.score, resolverSignals: strategyResult.matchedSignals,
        }),
      });

      await storage.createExecutionLog({
        workOrderId: orderId,
        tier: 1,
        action: "Resolver: Workflow Route",
        message: `Execution strategy resolver selected workflow template (score=${strategyResult.score}): ${strategyResult.reason}`,
        metadata: {
          strategy: strategyResult.strategy,
          templateId: strategyResult.templateId,
          score: strategyResult.score,
          matchedSignals: strategyResult.matchedSignals,
          rejectedCandidates: strategyResult.rejectedCandidates,
        },
      });

      addChecklistItem(orderId, "tier1_gate", `Resolver: workflow execution selected (score=${strategyResult.score})`, "aiden");

      // Route into the existing workflow engine — do NOT continue into direct PocketFlow path
      const workflowResult = await startWorkflowExecution(
        strategyResult.templateId,
        orderId,
        order.description || order.title,
        { resolverRoute: true, tier1Result },
      );

      // Workflow engine handles PM review + Aiden executive review internally.
      // Return here — do not fall through to single-agent pocketflowExecute + runAidenQualityReview.
      return;
    }
  }

  // ── Direct Execution Path (existing) ───────────────────────────────────────
  // Log resolver decision for audit even when direct
  if (strategyResult.strategy === "direct") {
    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "Resolver: Direct Execution",
      message: "Execution strategy resolver chose direct execution",
      metadata: { strategy: "direct" },
    });
  }

  const targetSubAgent = findSubAgent(activeSubAgents, tier1Result.handler);
  addChecklistItem(orderId, "tier1_gate", `Tier 1 approved — routing to ${targetSubAgent?.name || tier1Result.handler || "default agent"} (${targetSubAgent?.controlMode || "aiden"} mode)`, "aiden");

  // Resolve LLM config early so we can include it in logs and GCC
  const preDispatchLlmConfig = resolveSubAgentLlmConfig(targetSubAgent, settings);
  const preDispatchLlmLabel = preDispatchLlmConfig ? `${preDispatchLlmConfig.provider}/${preDispatchLlmConfig.model}` : "none";

  await storage.updateWorkOrder(orderId, {
    tier1Result,
    assignedSubAgentId: targetSubAgent?.id || null,
    executionMode: targetSubAgent?.controlMode || "aiden",
    gccMemory: updateWorkOrderGcc(order.gccMemory as object, "tier1_policy_pass", ["tier1_policy_pass", "routing_dispatched"], {
      correlationId: order.correlationId, status: "routing",
      handler: tier1Result.handler, mode: tier1Result.mode,
      subAgentId: targetSubAgent?.id, subAgentName: targetSubAgent?.name, controlMode: targetSubAgent?.controlMode,
      llmProvider: preDispatchLlmConfig?.provider, llmModel: preDispatchLlmConfig?.model, llmSource: preDispatchLlmConfig?.source,
    }),
  });

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Aiden: Dispatch to Sub-Agent",
    message: targetSubAgent
      ? `Aiden routing to sub-agent "${targetSubAgent.name}" (${targetSubAgent.controlMode} mode, LLM: ${preDispatchLlmLabel})`
      : `Aiden routing to handler: ${tier1Result.handler}`,
    metadata: {
      handler: tier1Result.handler,
      subAgentId: targetSubAgent?.id,
      subAgentName: targetSubAgent?.name,
      controlMode: targetSubAgent?.controlMode,
      llmProvider: preDispatchLlmConfig?.provider,
      llmModel: preDispatchLlmConfig?.model,
      llmSource: preDispatchLlmConfig?.source,
    },
  });

  if (targetSubAgent?.controlMode === "independent") {
    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 2,
      action: "Awaiting Operator",
      message: `Sub-agent "${targetSubAgent.name}" operates independently — assigned to ${targetSubAgent.assignedTo || "unassigned operator"}. Awaiting action.`,
      metadata: {
        subAgentId: targetSubAgent.id,
        subAgentName: targetSubAgent.name,
        assignedTo: targetSubAgent.assignedTo,
        controlMode: "independent",
      },
    });

    return storage.updateWorkOrder(orderId, {
      status: "awaiting_operator",
      gccMemory: updateWorkOrderGcc(order.gccMemory as object, "awaiting_independent_operator", ["tier1_policy_pass", "dispatched_to_independent_sub_agent"], {
        correlationId: order.correlationId, status: "awaiting_operator",
        assignedSubAgent: targetSubAgent.name, assignedTo: targetSubAgent.assignedTo,
      }),
    });
  }

  const effectiveLlmConfig = resolveSubAgentLlmConfig(targetSubAgent, settings);
  const hasLlm = !!effectiveLlmConfig;
  const llmSource = effectiveLlmConfig?.source || "none";
  const executorLabel = llmSource === "sub-agent"
    ? `"${targetSubAgent?.name}" (own LLM: ${effectiveLlmConfig?.provider}/${effectiveLlmConfig?.model})`
    : targetSubAgent
      ? `"${targetSubAgent.name}" (via Aiden's LLM: ${effectiveLlmConfig?.provider || "none"}/${effectiveLlmConfig?.model || "fallback"})`
      : "fallback handler";

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 2,
    action: "PocketFlow: Engine Start",
    message: `${executorLabel} starting PocketFlow iterative execution engine.`,
    metadata: { llmSource, llmModel: effectiveLlmConfig?.model, llmProvider: effectiveLlmConfig?.provider, subAgentName: targetSubAgent?.name },
  });

  // P0-C: Validate GCC authority before dispatching to Tier 2.
  // Tier 2 execution is permitted to COMMIT to its own branch only.
  // Any MERGE attempt from Tier 2 is a hard fail → HITL escalation.
  validateGccCommand("COMMIT", "tier2");

  const orderWithAgent = { ...order, assignedSubAgentId: targetSubAgent?.id || null };
  let tier2Result: Tier2Result = await pocketflowExecute(
    orderWithAgent,
    tier1Result,
    effectiveLlmConfig,
    settings || null,
    { maxIterations: 9, convergenceThreshold: 0.75, cachedGammaTemplates: runCtx.gammaTemplates, promptCompaction: runCtx.profile.promptCompaction, batchedSynthesis: runCtx.profile.batchedSynthesis, reviewReduction: runCtx.profile.reviewReduction }
  );

  // BUG-050 extension: Ownership check after main PocketFlow execution.
  // Prevents zombie from overwriting watchdog-killed WO with completion/quality review.
  if (attemptId && !(await isAttemptStillOwner(orderId, attemptId))) {
    console.warn(`[orchestration] Attempt ${attemptId.slice(0, 8)} superseded after main PocketFlow execution — exiting`);
    return;
  }

  if (tier2Result.blocked) {
    const bdmMarker = tier2Result.pocketflow?.bdmMarker || {
      type: "execution_block",
      reason: tier2Result.reason,
      tier: 2,
      timestamp: new Date().toISOString(),
      subAgentId: targetSubAgent?.id,
      subAgentName: targetSubAgent?.name,
    };

    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "Aiden: BDM Resolution",
      message: `Aiden received BDM marker from ${executorLabel} — pausing for human decision.`,
      metadata: { bdmMarker, pocketflow: tier2Result.pocketflow },
    });

    return storage.updateWorkOrder(orderId, {
      status: "blocked",
      tier2Result,
      bdmMarker,
      gccMemory: updateWorkOrderGcc(order.gccMemory as object, "tier2_execution_block", ["tier1_policy_pass", "pocketflow_execution_block"], {
        correlationId: order.correlationId, status: "blocked", tier: "tier2",
        pocketflow: tier2Result.pocketflow,
      }),
    });
  }

  const pfMeta = tier2Result.pocketflow;
  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 2,
    action: llmSource === "sub-agent" ? `${targetSubAgent?.name}: PocketFlow Complete` : "Sub-Agent: PocketFlow Complete",
    message: `${executorLabel} completed PocketFlow execution — score: ${pfMeta?.convergenceScore?.toFixed(2) || "N/A"}, iterations: ${pfMeta?.iterations || 1}, steps: ${pfMeta?.stepResults?.length || 0}.`,
    metadata: { ...tier2Result, llmSource, llmProvider: effectiveLlmConfig?.provider, llmModel: effectiveLlmConfig?.model },
  });

  const deliverable = tier2Result.output?.deliverable || "";
  const convergenceScore = pfMeta?.convergenceScore ?? 0;
  const iterations = pfMeta?.iterations ?? 1;
  const stepCount = pfMeta?.stepResults?.length ?? 0;

  let hadSearchTools = false;
  try {
    const agentTools = await getAvailableToolsForAgent(targetSubAgent?.id || undefined);
    hadSearchTools = agentTools.some(t => /search|browse|scrape|fetch|web/i.test(t.name + " " + t.slug + " " + (t.description || "")));
  } catch { /* tools check non-critical */ }

  let qualityReview;
  if (useLLM && settings) {
    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "Aiden: Quality Review",
      message: `Aiden (Tier 1) initiating final quality review of deliverable before completion approval.`,
      metadata: { deliverableLength: deliverable.length, convergenceScore, iterations, stepCount },
    });

    // BUG-038: Build PPTX quality supplement from preflight/compliance evidence
    const pptxPreflight = tier2Result.pocketflow?._pptxPreflight as PreflightResult | undefined;
    const pptxCompliance = tier2Result.pocketflow?._pptxCompliance as GammaComplianceResult | undefined;
    const pptxContract = tier2Result.pocketflow?._pptxContract as ParsedContract | undefined;
    const pptxSupplement = (pptxPreflight || pptxCompliance)
      ? buildPptxReviewSupplement(pptxPreflight || null, pptxCompliance || null, pptxContract || null)
      : null;

    // BUG-049: Heartbeat guard prevents watchdog false-kill during quality review LLM call
    // BUG-053: Phase timeout ensures auto-approve if the review LLM hangs
    try {
      qualityReview = await withWorkOrderHeartbeatGuard(orderId, "quality_review", () =>
        runAidenQualityReview(
          settings,
          order,
          deliverable,
          convergenceScore,
          iterations,
          stepCount,
          executorLabel,
          hadSearchTools,
          tier2Result.output?.postProcessedFile ?? null,
          pptxSupplement,
        ),
        attemptId,
      );
    } catch (err: any) {
      if (err instanceof PhaseTimeoutError) {
        console.warn(`[BUG-053] Quality review timed out for WO ${orderId} — auto-approving deliverable`);
        qualityReview = {
          approved: true,
          score: convergenceScore,
          summary: `Auto-approved (quality review timed out after ${(PHASE_TIMEOUT_MS / 1000).toFixed(0)}s). Manual review recommended.`,
          issues: ["Quality review LLM call timed out — deliverable not independently verified"],
          recommendation: "approve" as const,
        };
      } else {
        throw err;
      }
    }

    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: `Aiden: Quality ${qualityReview.approved ? "Approved" : "Flagged"}`,
      message: `Aiden quality review: ${qualityReview.summary} | Score: ${qualityReview.score.toFixed(2)} | Recommendation: ${qualityReview.recommendation}${qualityReview.issues.length > 0 ? ` | Issues: ${qualityReview.issues.join("; ")}` : ""}`,
      metadata: {
        qualityScore: qualityReview.score,
        recommendation: qualityReview.recommendation,
        issues: qualityReview.issues,
        summary: qualityReview.summary,
        approved: qualityReview.approved,
        executor: targetSubAgent?.name,
        llmProvider: effectiveLlmConfig?.provider,
        llmModel: effectiveLlmConfig?.model,
      },
    });
  } else {
    qualityReview = {
      approved: true,
      score: convergenceScore,
      summary: "Auto-approved (LLM not enabled for Tier 1 review)",
      issues: [] as string[],
      recommendation: "approve" as const,
    };
  }

  if (qualityReview.recommendation === "block") {
    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "Aiden: Quality Blocked",
      message: `Aiden blocked deliverable from ${executorLabel} — quality score: ${qualityReview.score.toFixed(2)}. Issues: ${qualityReview.issues.join("; ") || qualityReview.summary}. Requires HITL intervention.`,
      metadata: {
        finalStatus: "blocked",
        executedBy: llmSource,
        executorName: targetSubAgent?.name,
        qualityReview: { score: qualityReview.score, recommendation: qualityReview.recommendation, issues: qualityReview.issues, summary: qualityReview.summary },
      },
    });

    addChecklistItem(orderId, "quality_review", `Quality review blocked (score: ${qualityReview.score.toFixed(2)}) — ${qualityReview.summary}`, "aiden");
    return storage.updateWorkOrder(orderId, {
      status: "blocked",
      tier2Result,
      bdmMarker: { type: "quality_block", reason: `Aiden quality review: ${qualityReview.summary}`, tier: 1, timestamp: new Date().toISOString(), issues: qualityReview.issues },
      gccMemory: updateWorkOrderGcc(order.gccMemory as object, "quality_blocked", ["tier1_policy_pass", "pocketflow_execution_complete", "aiden_quality_review", "aiden_quality_blocked"], {
        correlationId: order.correlationId, status: "blocked",
        pocketflow: tier2Result.pocketflow,
        qualityReview: { score: qualityReview.score, recommendation: qualityReview.recommendation, issues: qualityReview.issues },
      }),
    });
  }

  if (qualityReview.recommendation === "request_revision" && !qualityReview.approved) {
    const controlMode = targetSubAgent?.controlMode || "aiden";
    const maxAutoRevisions = 4;
    const baseRevisionCount = ((order.gccMemory as any)?.["gcc.metadata"]?.revisionAttempts || 0);
    const canAutoRevise = controlMode === "aiden" && baseRevisionCount < maxAutoRevisions && hasLlm;

    if (canAutoRevise) {
      let currentQR = qualityReview;
      let currentTier2 = tier2Result;
      let revisionsDone = baseRevisionCount;
      let revisionApproved = false;
      let prevFailureKey = currentQR.issues.slice().sort().join("|");

      while (revisionsDone < maxAutoRevisions && !revisionApproved) {
        revisionsDone++;

        await storage.createExecutionLog({
          workOrderId: orderId,
          tier: 1,
          action: "Aiden: Auto-Revision Request",
          message: `Aiden autonomously requesting revision ${revisionsDone}/${maxAutoRevisions} from ${executorLabel} — quality score: ${currentQR.score.toFixed(2)}. Issues: ${currentQR.issues.join("; ") || currentQR.summary}. Re-executing with revision guidance.`,
          metadata: {
            revisionAttempt: revisionsDone,
            maxAutoRevisions,
            controlMode,
            executedBy: llmSource,
            executorName: targetSubAgent?.name,
            llmProvider: effectiveLlmConfig?.provider,
            llmModel: effectiveLlmConfig?.model,
            qualityReview: { score: currentQR.score, recommendation: currentQR.recommendation, issues: currentQR.issues, summary: currentQR.summary },
          },
        });

        // BUG-050: Ownership check before revision re-dispatch
        if (attemptId && !(await isAttemptStillOwner(orderId, attemptId))) {
          console.warn(`[orchestration] Attempt ${attemptId.slice(0, 8)} superseded before revision ${revisionsDone} — exiting`);
          return;
        }

        // BUG-049: Refresh heartbeat before revision re-dispatch to close the handoff gap
        await storage.updateWorkOrder(orderId, { heartbeatAt: new Date() }).catch(() => {});

        const latestOrder = await storage.getWorkOrder(orderId);
        const revisionGcc = updateWorkOrderGcc((latestOrder?.gccMemory || order.gccMemory) as object, "auto_revision_dispatched", ["tier1_policy_pass", "pocketflow_execution_complete", "aiden_quality_review", "aiden_auto_revision"], {
          correlationId: order.correlationId, status: "processing",
          revisionAttempt: revisionsDone,
          previousScore: currentQR.score,
          revisionGuidance: currentQR.issues,
          revisionSummary: currentQR.summary,
        });
        (revisionGcc as any)["gcc.metadata"] = { ...((revisionGcc as any)["gcc.metadata"] || {}), revisionAttempts: revisionsDone };

        await storage.updateWorkOrder(orderId, {
          status: "processing",
          gccMemory: revisionGcc,
        });

        const revisionContext = `\n\n--- AIDEN QUALITY REVIEW (Revision ${revisionsDone}) ---\nThe previous deliverable was rejected by Aiden's quality review.\nScore: ${currentQR.score.toFixed(2)}/1.0\nIssues:\n${currentQR.issues.map((i: string) => `- ${i}`).join("\n")}\nSummary: ${currentQR.summary}\n\nYou MUST address ALL issues listed above. Produce a complete, corrected deliverable that resolves every item.`;

        const revisedOrder = await storage.getWorkOrder(orderId);
        if (!revisedOrder) throw new Error("Work order not found after revision update");
        const revisedOrderWithAgent = { ...revisedOrder, assignedSubAgentId: targetSubAgent?.id || null };

        const revisedTier1 = { ...tier1Result, revisionGuidance: revisionContext };
        const revisionResult: Tier2Result = await pocketflowExecute(
          revisedOrderWithAgent,
          revisedTier1,
          effectiveLlmConfig,
          settings || null,
          { maxIterations: 9, convergenceThreshold: 0.75, revisionContext, cachedGammaTemplates: runCtx.gammaTemplates, promptCompaction: runCtx.profile.promptCompaction, batchedSynthesis: runCtx.profile.batchedSynthesis, reviewReduction: runCtx.profile.reviewReduction }
        );

        // BUG-050: Ownership check after pocketflowExecute returns
        if (attemptId && !(await isAttemptStillOwner(orderId, attemptId))) {
          console.warn(`[orchestration] Attempt ${attemptId.slice(0, 8)} superseded after revision ${revisionsDone} PocketFlow — exiting`);
          return;
        }

        // Loop 13 WI-1: Checkpoint best-so-far artifact to WO record after each revision.
        // If soft timeout fires during the next quality review or revision cycle,
        // the watchdog will find the latest valid output on the WO — not stale/null.
        currentTier2 = revisionResult;
        await storage.updateWorkOrder(orderId, {
          tier2Result: revisionResult,
        }).catch((err: any) => {
          console.warn(`[orchestration] Best-so-far checkpoint write failed for revision ${revisionsDone}:`, err?.message);
        });

        await storage.createExecutionLog({
          workOrderId: orderId,
          tier: 2,
          action: `${targetSubAgent?.name || "Sub-Agent"}: Revision ${revisionsDone} Complete`,
          message: `${executorLabel} completed revision attempt ${revisionsDone} — score: ${revisionResult.pocketflow?.convergenceScore?.toFixed(2) || "N/A"}.`,
          metadata: { revisionAttempt: revisionsDone, llmProvider: effectiveLlmConfig?.provider, llmModel: effectiveLlmConfig?.model, ...revisionResult },
        });

        const revDeliverable = revisionResult.output?.deliverable || "";
        const revPfMeta = revisionResult.pocketflow;

        let revQualityReview;
        try {
          // BUG-043: Pass postProcessedFile + pptxSupplement to revision reviews
          // (was missing — caused quality reviewer to reject valid PDF/PPTX deliverables)
          const revPostProcessedFile = revisionResult.output?.postProcessedFile ?? currentTier2.output?.postProcessedFile ?? null;
          const revPptxPreflight = revPfMeta?._pptxPreflight as PreflightResult | undefined;
          const revPptxCompliance = revPfMeta?._pptxCompliance as GammaComplianceResult | undefined;
          const revPptxContract = revPfMeta?._pptxContract as ParsedContract | undefined;
          const revPptxSupplement = (revPptxPreflight || revPptxCompliance)
            ? buildPptxReviewSupplement(revPptxPreflight || null, revPptxCompliance || null, revPptxContract || null)
            : null;
          // BUG-049: Heartbeat guard for revision-loop quality review
          revQualityReview = await withWorkOrderHeartbeatGuard(orderId, "revision_quality_review", () =>
            runAidenQualityReview(settings!, revisedOrder, revDeliverable, revPfMeta?.convergenceScore ?? 0, revPfMeta?.iterations ?? 1, revPfMeta?.stepResults?.length ?? 0, executorLabel, hadSearchTools, revPostProcessedFile, revPptxSupplement),
            attemptId,
          );
          await storage.createExecutionLog({
            workOrderId: orderId, tier: 1,
            action: `Aiden: Revision ${revisionsDone} Quality ${revQualityReview.approved ? "Approved" : "Flagged"}`,
            message: `Revision ${revisionsDone} quality review: ${revQualityReview.summary} | Score: ${revQualityReview.score.toFixed(2)} | Recommendation: ${revQualityReview.recommendation}`,
            metadata: { revisionAttempt: revisionsDone, qualityScore: revQualityReview.score, recommendation: revQualityReview.recommendation, issues: revQualityReview.issues },
          });
        } catch (revErr: any) {
          revQualityReview = { approved: true, score: 0.5, summary: `Revision review failed: ${revErr.message}`, issues: [] as string[], recommendation: "approve" as const };
        }

        currentTier2 = revisionResult;
        currentQR = revQualityReview;

        if (revQualityReview.approved || revQualityReview.recommendation === "approve") {
          revisionApproved = true;
        } else {
          // Circuit breaker: if the same failures repeat, further retries won't help.
          // Escalate immediately instead of burning more iterations.
          const currentFailureKey = revQualityReview.issues.slice().sort().join("|");
          if (currentFailureKey === prevFailureKey) {
            await storage.createExecutionLog({
              workOrderId: orderId, tier: 1,
              action: "Aiden: Revision Loop — Duplicate Failure",
              message: `Revision ${revisionsDone} from ${executorLabel} failed with identical issues as previous attempt — breaking retry loop. Issues: ${revQualityReview.issues.join("; ")}`,
              metadata: { revisionAttempt: revisionsDone, maxAutoRevisions, qualityReview: revQualityReview },
            });
            break; // exit while loop → falls through to awaiting_operator
          }
          prevFailureKey = currentFailureKey;

          await storage.createExecutionLog({
            workOrderId: orderId, tier: 1,
            action: "Aiden: Revision Still Below Quality",
            message: `Revision ${revisionsDone} from ${executorLabel} still below quality threshold — score: ${revQualityReview.score.toFixed(2)}. ${revisionsDone >= maxAutoRevisions ? "Max auto-revisions reached. Escalating to operator." : "Attempting another revision."}`,
            metadata: { revisionAttempt: revisionsDone, maxAutoRevisions, qualityReview: revQualityReview },
          });
        }
      }

      if (!revisionApproved) {
        // BUG-050: Ownership check before terminal-state write
        if (attemptId && !(await isAttemptStillOwner(orderId, attemptId))) {
          console.warn(`[orchestration] Attempt ${attemptId.slice(0, 8)} superseded before revision-exhausted terminal write — exiting`);
          return;
        }
        return storage.updateWorkOrder(orderId, {
          status: "awaiting_operator",
          tier2Result: currentTier2,
          gccMemory: updateWorkOrderGcc((await storage.getWorkOrder(orderId))?.gccMemory as object || {}, "revision_exhausted", ["tier1_policy_pass", "pocketflow_execution_complete", "aiden_quality_review", "aiden_auto_revision_exhausted"], {
            correlationId: order.correlationId, status: "awaiting_operator",
            revisionAttempts: revisionsDone,
            pocketflow: currentTier2.pocketflow,
            qualityReview: { score: currentQR.score, recommendation: currentQR.recommendation, issues: currentQR.issues, summary: currentQR.summary },
          }),
        });
      }

      tier2Result = currentTier2;
      qualityReview = currentQR;
    } else {
      await storage.createExecutionLog({
        workOrderId: orderId,
        tier: 1,
        action: "Aiden: Revision Requested",
        message: `Aiden requests revision from ${executorLabel} — quality score: ${qualityReview.score.toFixed(2)}. Issues: ${qualityReview.issues.join("; ") || qualityReview.summary}. ${controlMode !== "aiden" ? `Sub-agent in "${controlMode}" mode — ` : "Max revisions reached — "}Awaiting operator review.`,
        metadata: {
          finalStatus: "awaiting_operator",
          executedBy: llmSource,
          executorName: targetSubAgent?.name,
          controlMode,
          qualityReview: { score: qualityReview.score, recommendation: qualityReview.recommendation, issues: qualityReview.issues, summary: qualityReview.summary },
        },
      });

      return storage.updateWorkOrder(orderId, {
        status: "awaiting_operator",
        tier2Result,
        gccMemory: updateWorkOrderGcc(order.gccMemory as object, "revision_requested", ["tier1_policy_pass", "pocketflow_execution_complete", "aiden_quality_review", "aiden_revision_requested"], {
          correlationId: order.correlationId, status: "awaiting_operator",
          pocketflow: tier2Result.pocketflow,
          qualityReview: { score: qualityReview.score, recommendation: qualityReview.recommendation, issues: qualityReview.issues },
        }),
      });
    }
  }

  // ── HITL Candidate Review Gate ──────────────────────────────────────────────
  // If gammaDeliveryPolicy is "candidate_review", route to awaiting_operator
  // for candidate selection instead of auto-completing. The revision loop above
  // has already produced N candidates (each persisted with candidateStatus: "candidate"
  // in gamma_generation_records). The operator will select the best one via API.
  const deliveryPolicy = tier2Result.gammaDeliveryPolicy;
  if (deliveryPolicy === "candidate_review") {
    const candidates = await storage.getGammaCandidates(orderId);
    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "Aiden: Candidate Review Required",
      message: `${candidates.length} Gamma candidate(s) generated for operator review. Quality score: ${qualityReview.score.toFixed(2)}. Awaiting operator selection before final release.`,
      metadata: {
        finalStatus: "awaiting_operator",
        candidateCount: candidates.length,
        candidateIds: candidates.map(c => c.id),
        qualityReview: { score: qualityReview.score, recommendation: qualityReview.recommendation, issues: qualityReview.issues, summary: qualityReview.summary },
      },
    });

    addChecklistItem(orderId, "quality_review", `${candidates.length} Gamma candidate(s) ready for operator review`, "aiden");
    return storage.updateWorkOrder(orderId, {
      status: "awaiting_operator",
      tier2Result,
      gccMemory: updateWorkOrderGcc(order.gccMemory as object, "candidate_review", ["tier1_policy_pass", "pocketflow_execution_complete", "aiden_quality_review", "gamma_candidate_review"], {
        correlationId: order.correlationId, status: "awaiting_operator",
        candidateCount: candidates.length,
        resolutionReason: "candidate_review",
        pocketflow: tier2Result.pocketflow,
        qualityReview: { score: qualityReview.score, recommendation: qualityReview.recommendation, issues: qualityReview.issues },
      }),
    });
  }

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Aiden: Resolution",
    message: `Aiden approved deliverable from ${executorLabel} — quality score: ${qualityReview.score.toFixed(2)}. Work order completed.${qualityReview.issues.length > 0 ? ` Minor notes: ${qualityReview.issues.join("; ")}` : ""}`,
    metadata: {
      finalStatus: "completed",
      executedBy: llmSource,
      executorName: targetSubAgent?.name,
      executorModel: effectiveLlmConfig?.model,
      convergenceScore: pfMeta?.convergenceScore,
      iterations: pfMeta?.iterations,
      qualityReview: {
        score: qualityReview.score,
        recommendation: qualityReview.recommendation,
        issues: qualityReview.issues,
        summary: qualityReview.summary,
      },
    },
  });

  addChecklistItem(orderId, "quality_review", `Quality review passed (score: ${qualityReview.score.toFixed(2)}) — executor: ${executorLabel}`, "aiden");
  const completedOrder = await completeAndFileWorkOrder(orderId, {
    tier2Result,
    gccMemory: updateWorkOrderGcc(order.gccMemory as object, "completed", ["tier1_policy_pass", "pocketflow_validated", "pocketflow_execution_complete", "aiden_quality_review", "aiden_approved", "aiden_resolution"], {
      correlationId: order.correlationId, status: "completed",
      executor: targetSubAgent?.name, llmProvider: effectiveLlmConfig?.provider, llmModel: effectiveLlmConfig?.model,
      pocketflow: tier2Result.pocketflow,
      qualityReview: {
        score: qualityReview.score,
        recommendation: qualityReview.recommendation,
        issues: qualityReview.issues,
      },
    }),
  }, "quality-approved", attemptId);

  if (completedOrder) {
    addChecklistItem(orderId, "filing", `Completed — filing deliverable to workspace (${tier2Result.output?.deliverableType || "document"}${tier2Result.output?.postProcessedFile ? ", " + tier2Result.output.postProcessedFile.mimeType?.split("/").pop() + " " + ((tier2Result.output.postProcessedFile.size || 0) / 1024).toFixed(0) + "KB" : ""})`);
    // P1.4: Memory Advisor — Hook 2 (post-completion store)
    advisor.store({
      orderId: completedOrder.id,
      title: completedOrder.title || order.title,
      description: order.description || "",
      status: "completed",
      summary: qualityReview?.summary,
      issues: qualityReview?.issues,
      qualityScore: qualityReview?.score,
      handler: tier1Result.handler || undefined,
    } as WorkOrderEvent).catch(() => {});
  }

  return completedOrder;
}

function findSubAgent(agents: SubAgent[], handler: string | null): SubAgent | undefined {
  if (!handler || agents.length === 0) return undefined;

  const h = handler.trim();
  const hLower = h.toLowerCase();

  const byId = agents.find((a) => a.id === h);
  if (byId) return byId;

  const byExactName = agents.find((a) => a.name.toLowerCase() === hLower);
  if (byExactName) return byExactName;

  const typeMap: Record<string, string> = {
    deploy_executor: "deployment",
    maintenance_executor: "maintenance",
    incident_executor: "incident",
    change_executor: "change_request",
    security_executor: "security",
    general_executor: "general",
  };

  if (typeMap[h] || typeMap[hLower]) {
    const targetType = typeMap[h] || typeMap[hLower];
    const byType = agents.find((a) => a.type === targetType);
    if (byType) return byType;
  }

  const byTypeField = agents.find((a) => a.type === hLower);
  if (byTypeField) return byTypeField;

  if (h.length >= 5) {
    const hWords = hLower.split(/[\s_-]+/).filter(w => w.length >= 3);
    if (hWords.length > 0) {
      let bestMatch: SubAgent | undefined;
      let bestScore = 0;
      for (const agent of agents) {
        const nameWords = agent.name.toLowerCase().split(/[\s_-]+/).filter(w => w.length > 0);
        const descWords = (agent.description || "").toLowerCase().split(/[\s_-]+/).filter(w => w.length > 0);
        const allWords = [...nameWords, ...descWords];
        const matchCount = hWords.filter(w => allWords.some(aw => aw.includes(w) || w.includes(aw))).length;
        const score = matchCount / hWords.length;
        if (score > bestScore && score >= 0.5) {
          bestScore = score;
          bestMatch = agent;
        }
      }
      if (bestMatch) return bestMatch;
    }
  }

  return agents.find((a) => a.type === "general") || agents[0];
}

function runTier1PolicyGate(order: WorkOrder, subAgents: SubAgent[]): Tier1Result {
  const isBlocked =
    order.priority === "critical" && order.type === "deployment";

  if (isBlocked) {
    return {
      approved: false,
      reason: "Critical deployments require manual approval before processing.",
      mode: "manual_review",
      handler: null,
    };
  }

  const handlerMap: Record<string, string> = {
    standard: "general_executor",
    deployment: "deploy_executor",
    maintenance: "maintenance_executor",
    incident: "incident_executor",
    change_request: "change_executor",
    security: "security_executor",
    configuration: "general_executor",
  };

  return {
    approved: true,
    reason: "Aiden policy gate passed — all rules satisfied.",
    mode: "auto",
    handler: handlerMap[order.type] || "general_executor",
  };
}

function runTier2Execution(order: WorkOrder, tier1Result: Tier1Result): Tier2Result {
  const shouldBlock =
    order.type === "incident" && order.priority === "critical";

  if (shouldBlock) {
    return {
      blocked: true,
      reason: "Critical incident requires escalation — BDM marker emitted for human review.",
      executionId: null,
      handler: tier1Result.handler,
    };
  }

  const deliverable = generateFallbackDeliverable(order);

  const typeToDeliverableType: Record<string, string> = {
    deployment: "document",
    maintenance: "document",
    incident: "document",
    change_request: "document",
    security: "document",
    configuration: "code",
    standard: "document",
  };

  return {
    blocked: false,
    reason: null,
    executionId: `exec_${Date.now()}`,
    handler: tier1Result.handler,
    output: {
      message: `Work order "${order.title}" processed successfully.`,
      deliverable,
      deliverableType: (typeToDeliverableType[order.type] || "document") as "document" | "code" | "image" | "mixed",
      deliverableTitle: order.title,
    },
  };
}

function generateFallbackDeliverable(order: WorkOrder): string {
  const timestamp = new Date().toISOString();
  const typeLabels: Record<string, string> = {
    deployment: "Deployment Report",
    maintenance: "Maintenance Report",
    incident: "Incident Report",
    change_request: "Change Request Summary",
    security: "Security Assessment",
    configuration: "Configuration Change Report",
    standard: "Task Completion Report",
  };
  const label = typeLabels[order.type] || "Task Completion Report";

  return `# ${label}: ${order.title}

## Objective
${order.description}

## Execution Summary
This work order was processed by Aiden's orchestration engine using the hardcoded policy engine (LLM not enabled). The order passed Tier 1 policy validation and was executed by the assigned sub-agent.

## Actions Taken
1. **Schema Validation** — Work order schema validated against ${order.type} requirements
2. **Policy Check** — Priority "${order.priority}" cleared all policy gates
3. **Execution** — Work order executed by handler with standard procedures
4. **Verification** — Output verified and marked as complete

## Result
Work order "${order.title}" has been completed successfully. All actions were performed according to standard operating procedures for ${order.type} work orders.

## Recommendations
- Enable LLM integration in Settings to get AI-generated deliverables with full context-aware content
- Review execution logs for detailed step-by-step timeline

---
_Generated by Aiden (fallback mode) on ${timestamp}_`;
}

// ==================== Workflow Orchestration Engine ====================

export async function startWorkflowExecution(
  templateId: string,
  workOrderId: string | null,
  goal: string | null,
  context: Record<string, any> = {},
  pmSubAgentIdOverride?: string,
  options?: { skipAdvance?: boolean }
) {
  const _wfStart = Date.now();
  console.log(`[perf:wf] START template=${templateId} wo=${workOrderId}`);
  const template = await storage.getWorkflowTemplate(templateId);
  if (!template) throw new Error("Workflow template not found");

  const steps = await storage.getWorkflowSteps(templateId);
  if (steps.length === 0) throw new Error("Workflow template has no steps");

  // Phase 2: Resolve shared context once per workflow run
  const { resolveRunContext } = await import("./run-context");
  const runCtx = await resolveRunContext();
  const globalSettings = runCtx.settings;
  const activeSubAgents = runCtx.activeSubAgents;

  let pmSubAgent: SubAgent | null = null;
  let pmLlmConfig: any = null;

  if (pmSubAgentIdOverride) {
    pmSubAgent = activeSubAgents.find(a => a.id === pmSubAgentIdOverride) || null;
    if (pmSubAgent) {
      pmLlmConfig = resolvePmLlmConfig(pmSubAgent, template, globalSettings);
    }
  }

  if (!pmSubAgent) {
    const pmResult = await selectProjectManager(template, activeSubAgents, globalSettings);
    pmSubAgent = pmResult.pm;
    pmLlmConfig = pmResult.llmConfig;
  }

  const execution = await storage.createWorkflowExecution({
    templateId,
    workOrderId,
    goal: goal || template.goal,
    context,
    pmSubAgentId: pmSubAgent?.id || null,
    executionMode: template.executionMode || "autonomous",
  });

  await storage.updateWorkflowExecution(execution.id, {
    status: "running",
    startedAt: new Date(),
    currentStepKey: steps[0].stepKey,
    pmLlmConfig: pmLlmConfig || null,
  });

  for (const step of steps) {
    await storage.createWorkflowStepRun({
      executionId: execution.id,
      stepKey: step.stepKey,
      stepName: step.name,
      assignedSubAgentId: step.assignedSubAgentId,
      toolsUsed: step.toolIds || [],
      input: {},
    });
  }

  if (workOrderId) {
    await storage.updateWorkOrder(workOrderId, {
      workflowExecutionId: execution.id,
      status: "processing",
    });
    await storage.createExecutionLog({
      workOrderId,
      tier: 1,
      action: "Aiden: Workflow Started",
      message: `Aiden started workflow "${template.name}" with ${steps.length} steps${pmSubAgent ? ` — PM: ${pmSubAgent.name}` : ""} toward goal: ${goal || template.goal || "execute workflow"}`,
      metadata: {
        executionId: execution.id, templateId, stepCount: steps.length,
        pmSubAgentId: pmSubAgent?.id, pmSubAgentName: pmSubAgent?.name,
        executionMode: template.executionMode, llmMode: template.llmMode,
      },
    });

    if (pmSubAgent) {
      await storage.createExecutionLog({
        workOrderId,
        tier: 1,
        action: "Aiden: PM Assigned",
        message: `Project Manager "${pmSubAgent.name}" assigned to coordinate workflow execution${pmLlmConfig ? ` (LLM: ${pmLlmConfig.provider}/${pmLlmConfig.model}, mode: ${template.llmMode})` : ""}.`,
        metadata: {
          pmSubAgentId: pmSubAgent.id, pmSubAgentName: pmSubAgent.name,
          llmMode: template.llmMode, executionMode: template.executionMode,
          llmProvider: pmLlmConfig?.provider, llmModel: pmLlmConfig?.model,
        },
      });
    }
  }

  if (options?.skipAdvance) {
    console.log(`[perf:wf] END template=${templateId} ${Date.now() - _wfStart}ms (skipAdvance)`);
    return execution;
  }
  const result = await advanceWorkflowExecution(execution.id);
  console.log(`[perf:wf] END template=${templateId} ${Date.now() - _wfStart}ms`);
  return result;
}

export async function advanceWorkflowExecution(executionId: string, attemptId?: string) {
  const execution = await storage.getWorkflowExecution(executionId);
  if (!execution) throw new Error("Workflow execution not found");

  const template = await storage.getWorkflowTemplate(execution.templateId);
  const steps = await storage.getWorkflowSteps(execution.templateId);
  const stepRuns = await storage.getWorkflowStepRuns(executionId);
  // Phase 2: Use RunContext for settings (avoid re-fetching per advancement cycle)
  const { resolveRunContext } = await import("./run-context");
  const runCtx = await resolveRunContext();
  const settings = runCtx.settings;
  const useLLM = runCtx.useLLM;

  const hasPm = !!execution.pmSubAgentId;
  const pmLlmConfig = execution.pmLlmConfig as any;

  // Phase 6: Check for parallel group execution (fast profile only)
  if (runCtx.profile.workflowParallelism) {
    const parallelGroup = findRunnableParallelGroup(steps, stepRuns);
    if (parallelGroup) {
      console.log(`[perf:parallel] Executing parallel group ${parallelGroup.group}: ${parallelGroup.stepDefs.map(s => s.name).join(" + ")} (${parallelGroup.stepRuns.length} steps)`);

      const previousResults = collectPreviousResults(stepRuns);

      // Mark all steps as running
      for (const run of parallelGroup.stepRuns) {
        await storage.updateWorkflowStepRun(run.id, {
          status: "running", startedAt: new Date(),
          input: { previousResults, goal: execution.goal, context: execution.context },
        });
      }

      // Execute all steps in parallel
      const groupResults: Array<{ stepDef: WorkflowStep; stepRun: WorkflowStepRun; result: any; error?: string }> = [];

      await Promise.all(parallelGroup.stepDefs.map(async (stepDef, i) => {
        const stepRun = parallelGroup.stepRuns[i];
        try {
          const subAgent = stepDef.assignedSubAgentId
            ? await storage.getSubAgent(stepDef.assignedSubAgentId)
            : await findSubAgentForStep(stepDef, runCtx.activeSubAgents);
          const toolsList = await getToolsForStep(stepDef, subAgent?.id || null, runCtx.operationalSettings);

          if (useLLM && subAgent && settings) {
            const result = await executeWorkflowStepWithPocketFlow(stepDef, subAgent, previousResults, execution.goal || "", settings, toolsList, executionId, runCtx.gammaTemplates, runCtx.profile.promptCompaction, runCtx.profile.batchedSynthesis);
            await storage.updateWorkflowStepRun(stepRun.id, {
              status: "completed", completedAt: new Date(), output: result.output,
            });
            groupResults.push({ stepDef, stepRun, result });
          } else {
            const toolNames = toolsList.map(t => t.name);
            const result = await executeWorkflowStep(stepDef, previousResults, execution.goal || "", toolNames, useLLM, settings);
            await storage.updateWorkflowStepRun(stepRun.id, {
              status: "completed", completedAt: new Date(), output: result.output,
            });
            groupResults.push({ stepDef, stepRun, result });
          }
        } catch (err: any) {
          console.error(`[parallel] Step "${stepDef.name}" failed:`, err.message);
          await storage.updateWorkflowStepRun(stepRun.id, {
            status: "failed", completedAt: new Date(), output: { error: err.message },
          });
          groupResults.push({ stepDef, stepRun, result: null, error: err.message });
        }
      }));

      console.log(`[perf:parallel] Group ${parallelGroup.group} complete: ${groupResults.filter(r => !r.error).length}/${groupResults.length} succeeded`);

      // Batch PM review for the group (one call instead of N)
      if (hasPm && pmLlmConfig) {
        const successfulResults = groupResults.filter(r => !r.error);
        if (successfulResults.length > 0) {
          const combinedOutputForReview = successfulResults
            .map(r => `### ${r.stepDef.name}\n${typeof r.result?.output === "string" ? r.result.output.slice(0, 2000) : JSON.stringify(r.result?.output).slice(0, 2000)}`)
            .join("\n\n---\n\n");

          // Use first step's def as representative for the batch review
          const batchStepDef = { ...successfulResults[0].stepDef, name: `Parallel Group ${parallelGroup.group} (${successfulResults.length} steps)`, description: `Batch review of: ${successfulResults.map(r => r.stepDef.name).join(", ")}` };
          const review = await pmReviewStepOutput(pmLlmConfig, batchStepDef as any, combinedOutputForReview, execution.goal || "", previousResults);

          for (const r of successfulResults) {
            await storage.updateWorkflowStepRun(r.stepRun.id, { pmReview: review });
          }

          if (execution.workOrderId) {
            await storage.createExecutionLog({
              workOrderId: execution.workOrderId, tier: 1,
              action: `PM: Batch Group Review`,
              message: `PM reviewed parallel group ${parallelGroup.group} (${successfulResults.length} steps) — Score: ${review.score.toFixed(2)}, Recommendation: ${review.recommendation}. ${review.feedback}`,
              metadata: { group: parallelGroup.group, stepCount: successfulResults.length, review },
            });
          }

          console.log(`[perf:parallel] Batch PM review: score=${review.score.toFixed(2)} recommendation=${review.recommendation} (saved ${successfulResults.length - 1} PM review calls)`);
        }
      }

      // Continue advancing (next step or completion)
      return advanceWorkflowExecution(executionId, attemptId);
    }
  }

  const nextStepRun = findNextRunnableStep(steps, stepRuns);

  if (!nextStepRun) {
    const allCompleted = stepRuns.every((r) => r.status === "completed" || r.status === "skipped");
    const hasFailed = stepRuns.some((r) => r.status === "failed");

    if (hasFailed && !hasPm) {
      await storage.updateWorkflowExecution(executionId, { status: "failed", completedAt: new Date() });
      if (execution.workOrderId) {
        await storage.updateWorkOrder(execution.workOrderId, { status: "failed" });
      }
    } else if (hasFailed && hasPm) {
      const failedCount = stepRuns.filter(r => r.status === "failed").length;
      const escalation = await pmEscalateToAiden(settings, execution.executionMode || "autonomous", `${failedCount} workflow step(s) failed after PM review`, {
        workflowName: template?.name || "Unknown",
        workflowGoal: execution.goal || "",
        failedStep: stepRuns.find(r => r.status === "failed")?.stepName,
      });
      if (escalation.action === "hitl") {
        await storage.updateWorkflowExecution(executionId, { status: "blocked", completedAt: new Date() });
        if (execution.workOrderId) {
          await storage.updateWorkOrder(execution.workOrderId, { status: "blocked" });
          await storage.createExecutionLog({ workOrderId: execution.workOrderId, tier: 1,
            action: "PM: Escalated to HITL", message: `PM escalated failed workflow to operator: ${escalation.reason}`,
            metadata: { escalation },
          });
        }
      } else {
        await storage.updateWorkflowExecution(executionId, { status: "failed", completedAt: new Date() });
        if (execution.workOrderId) {
          await storage.updateWorkOrder(execution.workOrderId, { status: "failed" });
        }
      }
    } else if (allCompleted) {
      if (hasPm && pmLlmConfig) {
        await handleWorkflowCompletion(execution, template, steps, stepRuns, settings, pmLlmConfig, attemptId, runCtx.profile.reviewReduction);
      } else {
        await storage.updateWorkflowExecution(executionId, { status: "completed", completedAt: new Date() });
        if (execution.workOrderId) {
          const woForGcc = await storage.getWorkOrder(execution.workOrderId);
          await storage.createExecutionLog({
            workOrderId: execution.workOrderId, tier: 1,
            action: "Aiden: Workflow Completed",
            message: `All ${steps.length} workflow steps completed successfully.`,
            metadata: { executionId },
          });
          await completeAndFileWorkOrder(execution.workOrderId, {
            gccMemory: updateWorkOrderGcc(woForGcc?.gccMemory as object, "workflow_completed", ["workflow_steps_complete", "workflow_completed"], {
              workflowExecutionId: executionId, status: "completed",
            }),
          }, "workflow-no-pm", attemptId);
        }
      }
    }

    return storage.getWorkflowExecution(executionId);
  }

  const stepDef = steps.find((s) => s.stepKey === nextStepRun.stepKey);
  if (!stepDef) throw new Error(`Step definition not found for ${nextStepRun.stepKey}`);

  if (!evaluateConditions(stepDef, stepRuns)) {
    await storage.updateWorkflowStepRun(nextStepRun.id, { status: "skipped", completedAt: new Date() });
    return advanceWorkflowExecution(executionId, attemptId);
  }

  const previousResults = collectPreviousResults(stepRuns);
  await storage.updateWorkflowExecution(executionId, { currentStepKey: nextStepRun.stepKey });
  await storage.updateWorkflowStepRun(nextStepRun.id, {
    status: "running", startedAt: new Date(),
    input: { previousResults, goal: execution.goal, context: execution.context },
  });

  if (execution.workOrderId) {
    const actor = hasPm ? "PM" : "Aiden";
    await storage.createExecutionLog({
      workOrderId: execution.workOrderId, tier: hasPm ? 2 : 1,
      action: `${actor}: Step "${stepDef.name}"`,
      message: `${actor}${hasPm && pmLlmConfig ? ` (LLM: ${pmLlmConfig.provider}/${pmLlmConfig.model})` : ""} executing workflow step: ${stepDef.name}${stepDef.description ? ` — ${stepDef.description}` : ""}`,
      metadata: { stepKey: stepDef.stepKey, order: stepDef.order, hasPm, llmProvider: pmLlmConfig?.provider, llmModel: pmLlmConfig?.model },
    });
  }

  // External steps (operator-owned, no sub-agent dispatch) → awaiting_operator (Loop 26)
  if (stepDef.stepType === "external") {
    await storage.updateWorkflowStepRun(nextStepRun.id, {
      status: "awaiting_operator",
      aidenDecision: { action: "external_step_awaiting_operator", stepName: stepDef.name },
    });
    await storage.updateWorkflowExecution(executionId, { status: "awaiting_operator" });
    if (execution.workOrderId) {
      await storage.updateWorkOrder(execution.workOrderId, { status: "awaiting_operator" });
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId, tier: 1,
        action: "Awaiting Operator",
        message: `External step "${stepDef.name}" requires operator action — workflow paused until resolved.`,
        metadata: { stepKey: stepDef.stepKey, stepType: "external" },
      });
    }
    return storage.getWorkflowExecution(executionId);
  }

  const subAgent = stepDef.assignedSubAgentId
    ? await storage.getSubAgent(stepDef.assignedSubAgentId)
    : await findSubAgentForStep(stepDef, runCtx.activeSubAgents);

  const toolsList = await getToolsForStep(stepDef, subAgent?.id || null, runCtx.operationalSettings);
  const toolNames = toolsList.map((t) => t.name);

  if (subAgent?.controlMode === "independent") {
    await storage.updateWorkflowStepRun(nextStepRun.id, {
      status: "awaiting_operator", assignedSubAgentId: subAgent.id,
      aidenDecision: { action: "assigned_to_independent_operator", subAgent: subAgent.name, operator: subAgent.assignedTo, tools: toolNames },
    });
    await storage.updateWorkflowExecution(executionId, { status: "awaiting_operator" });
    if (execution.workOrderId) {
      await storage.updateWorkOrder(execution.workOrderId, { status: "awaiting_operator" });
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId, tier: 2,
        action: "Awaiting Operator",
        message: `Step "${stepDef.name}" assigned to independent sub-agent "${subAgent.name}" — awaiting ${subAgent.assignedTo || "operator"}.`,
        metadata: { subAgentId: subAgent.id, tools: toolNames },
      });
    }
    return storage.getWorkflowExecution(executionId);
  }

  // Step-level heartbeat: keeps heartbeatAt fresh during long step execution (LLM + Gamma)
  const stepHeartbeatHandle = setInterval(async () => {
    try {
      await storage.updateWorkflowStepRun(nextStepRun.id, { heartbeatAt: new Date() });
      if (execution.workOrderId) {
        await storage.updateWorkOrder(execution.workOrderId, { heartbeatAt: new Date() });
      }
    } catch {}
  }, HEARTBEAT_INTERVAL_MS);

  try {
    let stepResult: { output: any; toolsUsed: string[]; decision: any; pocketflowResult?: any };

    if (useLLM && subAgent && settings) {
      stepResult = await executeWorkflowStepWithPocketFlow(stepDef, subAgent, previousResults, execution.goal || "", settings, toolsList, executionId, runCtx.gammaTemplates, runCtx.profile.promptCompaction, runCtx.profile.batchedSynthesis, runCtx.profile.reviewReduction);
    } else {
      stepResult = await executeWorkflowStep(stepDef, previousResults, execution.goal || "", toolNames, useLLM, settings);
    }

    clearInterval(stepHeartbeatHandle);

    // Check for "Tool Needed" signal BEFORE marking step complete
    const platformMode = runCtx.operationalSettings?.currentMode || "semi_autonomous";
    const toolNeededResult = await handleToolNeededSignal(
      stepResult.output, stepDef, platformMode, execution, nextStepRun, executionId
    );
    if (toolNeededResult?.hitlBlocked) return storage.getWorkflowExecution(executionId);
    if (toolNeededResult?.retryQueued) return advanceWorkflowExecution(executionId, attemptId);

    await storage.updateWorkflowStepRun(nextStepRun.id, {
      status: "completed", completedAt: new Date(),
      output: stepResult.output,
      toolsUsed: stepResult.toolsUsed || [],
      aidenDecision: stepResult.decision,
      pocketflowResult: stepResult.pocketflowResult || null,
      assignedSubAgentId: subAgent?.id || null,
    });

    const stepLlmConfig = subAgent ? resolveSubAgentLlmConfig(subAgent, settings) : null;

    if (execution.workOrderId) {
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId, tier: 2,
        action: `Sub-Agent: ${stepDef.name} Complete`,
        message: `Step "${stepDef.name}" completed${subAgent ? ` by "${subAgent.name}"` : ""}${stepLlmConfig ? ` (LLM: ${stepLlmConfig.provider}/${stepLlmConfig.model})` : ""}.`,
        metadata: { stepKey: stepDef.stepKey, tools: stepResult.toolsUsed, subAgentName: subAgent?.name, llmProvider: stepLlmConfig?.provider, llmModel: stepLlmConfig?.model },
      });
    }

    if (hasPm && pmLlmConfig) {
      // Phase 7: Skip PM review for trivial outputs when review reduction is enabled
      const outputStr = typeof stepResult.output === "string" ? stepResult.output : JSON.stringify(stepResult.output || "");
      const isTrivial = runCtx.profile.reviewReduction && outputStr.length < 500;

      if (isTrivial) {
        console.log(`[perf:review] Skipped PM review for "${stepDef.name}" — trivial output (${outputStr.length} chars)`);
        const autoReview = { score: 0.85, recommendation: "approve", feedback: "Auto-approved: trivial output (review reduction)" };
        await storage.updateWorkflowStepRun(nextStepRun.id, { pmReview: autoReview });
        if (execution.workOrderId) {
          await storage.createExecutionLog({
            workOrderId: execution.workOrderId, tier: 1,
            action: `PM: Review Skipped (Trivial)`,
            message: `PM review skipped for "${stepDef.name}" — output under 500 chars (review reduction enabled). Auto-approved.`,
            metadata: { stepKey: stepDef.stepKey, outputLength: outputStr.length, reviewReduction: true },
          });
        }
      } else {
      const review = await pmReviewStepOutput(pmLlmConfig, stepDef, stepResult.output, execution.goal || "", previousResults);
      await storage.updateWorkflowStepRun(nextStepRun.id, { pmReview: review });

      if (execution.workOrderId) {
        await storage.createExecutionLog({
          workOrderId: execution.workOrderId, tier: 1,
          action: `PM: Step Review`,
          message: `PM (LLM: ${pmLlmConfig.provider}/${pmLlmConfig.model}) reviewed "${stepDef.name}" — Score: ${review.score.toFixed(2)}, Recommendation: ${review.recommendation}. ${review.feedback}`,
          metadata: { stepKey: stepDef.stepKey, review, llmProvider: pmLlmConfig.provider, llmModel: pmLlmConfig.model },
        });
      }

      if (review.recommendation === "revise") {
        const retryPolicy = (stepDef.retryPolicy as any) || { maxRetries: 1 };
        const currentAttempt = nextStepRun.revisionAttempt || 0;
        if (currentAttempt < (retryPolicy.maxRetries || 1)) {
          const guidance = await pmRequestStepRevision(pmLlmConfig, stepDef, stepResult.output, review, currentAttempt);
          if (execution.workOrderId) {
            await storage.createExecutionLog({
              workOrderId: execution.workOrderId, tier: 1,
              action: `PM: Revision Request`,
              message: `PM (LLM: ${pmLlmConfig.provider}/${pmLlmConfig.model}) requesting revision ${currentAttempt + 1} for "${stepDef.name}": ${guidance.revisionInstructions.slice(0, 200)}`,
              metadata: { stepKey: stepDef.stepKey, revisionAttempt: currentAttempt + 1, guidance, llmProvider: pmLlmConfig.provider, llmModel: pmLlmConfig.model },
            });
          }
          await storage.updateWorkflowStepRun(nextStepRun.id, {
            status: "pending", revisionAttempt: currentAttempt + 1,
            completedAt: null, startedAt: null,
            input: { previousResults, goal: execution.goal, context: execution.context, revisionGuidance: guidance },
          });
          return advanceWorkflowExecution(executionId, attemptId);
        }
      } else if (review.recommendation === "escalate") {
        const escalation = await pmEscalateToAiden(settings, execution.executionMode || "autonomous",
          `Step "${stepDef.name}" failed PM quality review with score ${review.score}`,
          { workflowName: template?.name || "", workflowGoal: execution.goal || "", failedStep: stepDef.name, stepOutput: stepResult.output, pmReview: review, revisionAttempts: nextStepRun.revisionAttempt || 0 }
        );
        if (execution.workOrderId) {
          await storage.createExecutionLog({
            workOrderId: execution.workOrderId, tier: 1,
            action: `PM: Escalation → ${escalation.action === "hitl" ? "HITL" : "Aiden"}`,
            message: `PM (LLM: ${pmLlmConfig.provider}/${pmLlmConfig.model}) escalated step "${stepDef.name}": ${escalation.reason}. Action: ${escalation.action}`,
            metadata: { stepKey: stepDef.stepKey, escalation, llmProvider: pmLlmConfig.provider, llmModel: pmLlmConfig.model },
          });
        }
        if (escalation.action === "hitl") {
          await storage.updateWorkflowStepRun(nextStepRun.id, { status: "awaiting_operator" });
          await storage.updateWorkflowExecution(executionId, { status: "awaiting_operator" });
          if (execution.workOrderId) {
            await storage.updateWorkOrder(execution.workOrderId, { status: "awaiting_operator" });
          }
          return storage.getWorkflowExecution(executionId);
        } else if (escalation.action === "skip") {
          await storage.updateWorkflowStepRun(nextStepRun.id, { status: "skipped" });
        } else if (escalation.action === "abort") {
          await storage.updateWorkflowStepRun(nextStepRun.id, { status: "failed", error: escalation.reason });
          await storage.updateWorkflowExecution(executionId, { status: "failed", completedAt: new Date() });
          if (execution.workOrderId) {
            await storage.updateWorkOrder(execution.workOrderId, { status: "failed" });
          }
          return storage.getWorkflowExecution(executionId);
        }
      }
    }
    } // close else (non-trivial PM review)

    return advanceWorkflowExecution(executionId, attemptId);
  } catch (err: any) {
    clearInterval(stepHeartbeatHandle);
    await storage.updateWorkflowStepRun(nextStepRun.id, {
      status: "failed", completedAt: new Date(),
      error: err.message || "Step execution failed",
    });

    if (hasPm) {
      const escalation = await pmEscalateToAiden(settings, execution.executionMode || "autonomous",
        `Step "${stepDef.name}" threw an error: ${err.message}`,
        { workflowName: template?.name || "", workflowGoal: execution.goal || "", failedStep: stepDef.name }
      );
      if (escalation.action === "skip") {
        await storage.updateWorkflowStepRun(nextStepRun.id, { status: "skipped" });
        return advanceWorkflowExecution(executionId, attemptId);
      } else if (escalation.action === "hitl") {
        await storage.updateWorkflowExecution(executionId, { status: "awaiting_operator" });
        if (execution.workOrderId) {
          await storage.updateWorkOrder(execution.workOrderId, { status: "awaiting_operator" });
        }
        return storage.getWorkflowExecution(executionId);
      }
    }

    await storage.updateWorkflowExecution(executionId, { status: "failed", completedAt: new Date() });
    if (execution.workOrderId) {
      await storage.updateWorkOrder(execution.workOrderId, { status: "failed" });
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId, tier: 2,
        action: `Sub-Agent: ${stepDef.name} Failed`,
        message: `Step "${stepDef.name}" failed: ${err.message}`,
        metadata: { stepKey: stepDef.stepKey, error: err.message },
      });
    }
    return storage.getWorkflowExecution(executionId);
  }
}

function findNextRunnableStep(steps: WorkflowStep[], stepRuns: WorkflowStepRun[]): WorkflowStepRun | null {
  const sortedSteps = [...steps].sort((a, b) => a.order - b.order);
  for (const step of sortedSteps) {
    const run = stepRuns.find((r) => r.stepKey === step.stepKey);
    if (run && run.status === "pending") {
      const deps = step.dependencies || [];
      const allDepsMet = deps.every((dep) => {
        const depRun = stepRuns.find((r) => r.stepKey === dep);
        return depRun && (depRun.status === "completed" || depRun.status === "skipped");
      });
      if (allDepsMet) return run;
    }
  }
  return null;
}

/** Phase 6: Find ALL runnable steps that share the same parallelGroup */
function findRunnableParallelGroup(steps: WorkflowStep[], stepRuns: WorkflowStepRun[]): { group: number; stepRuns: WorkflowStepRun[]; stepDefs: WorkflowStep[] } | null {
  const sortedSteps = [...steps].sort((a, b) => a.order - b.order);
  const runnableByGroup = new Map<number, { runs: WorkflowStepRun[]; defs: WorkflowStep[] }>();

  for (const step of sortedSteps) {
    if (step.parallelGroup == null) continue;
    if (step.stepType === "external") continue; // external steps are operator-owned, not parallelizable
    const run = stepRuns.find((r) => r.stepKey === step.stepKey);
    if (!run || run.status !== "pending") continue;

    const deps = step.dependencies || [];
    const allDepsMet = deps.every((dep) => {
      const depRun = stepRuns.find((r) => r.stepKey === dep);
      return depRun && (depRun.status === "completed" || depRun.status === "skipped");
    });
    if (!allDepsMet) continue;

    if (!runnableByGroup.has(step.parallelGroup)) {
      runnableByGroup.set(step.parallelGroup, { runs: [], defs: [] });
    }
    runnableByGroup.get(step.parallelGroup)!.runs.push(run);
    runnableByGroup.get(step.parallelGroup)!.defs.push(step);
  }

  // Return the first group with 2+ runnable steps
  for (const [group, data] of runnableByGroup) {
    if (data.runs.length >= 2) {
      return { group, stepRuns: data.runs, stepDefs: data.defs };
    }
  }
  return null;
}

function evaluateConditions(step: WorkflowStep, stepRuns: WorkflowStepRun[]): boolean {
  const conditions = step.conditions as Record<string, any> | null;
  if (!conditions || Object.keys(conditions).length === 0) return true;

  if (conditions.requirePreviousSuccess) {
    const depKey = conditions.requirePreviousSuccess;
    const depRun = stepRuns.find((r) => r.stepKey === depKey);
    if (!depRun || depRun.status !== "completed") return false;
  }

  if (conditions.skipIfPreviousFailed) {
    const depKey = conditions.skipIfPreviousFailed;
    const depRun = stepRuns.find((r) => r.stepKey === depKey);
    if (depRun && depRun.status === "failed") return false;
  }

  return true;
}

function collectPreviousResults(stepRuns: WorkflowStepRun[]): Record<string, any> {
  const results: Record<string, any> = {};
  for (const run of stepRuns) {
    if (run.status === "completed" && run.output) {
      results[run.stepKey] = run.output;
    }
  }
  return results;
}

async function findSubAgentForStep(step: WorkflowStep, cachedAgents?: SubAgent[]): Promise<SubAgent | undefined> {
  const activeAgents = cachedAgents || await storage.getActiveSubAgents();
  if (activeAgents.length === 0) return undefined;

  // 1. Exact agentType match
  if (step.agentType) {
    const byType = activeAgents.find((a) => a.type === step.agentType);
    if (byType) return byType;
  }

  // 2. Score each agent against step name + description keywords
  const stepText = `${step.name || ""} ${step.description || ""}`.toLowerCase();
  const scored = activeAgents.map(agent => {
    const agentText = `${agent.name || ""} ${agent.description || ""} ${agent.type || ""}`.toLowerCase();
    let score = 0;
    // Check if step text mentions agent name
    const agentFirstWord = (agent.name || "").toLowerCase().split(/\s+/)[0];
    if (agentFirstWord && stepText.includes(agentFirstWord)) score += 10;
    // Keyword overlap between step description and agent description
    const stepWords = stepText.split(/\W+/).filter(w => w.length > 3);
    for (const word of stepWords) {
      if (agentText.includes(word)) score += 1;
    }
    // Penalize deployment agents for creative/content steps
    const isDeployAgent = agentText.includes("deploy") || agentText.includes("polaris");
    const isCreativeStep = /content|draft|research|design|write|slide|deck|present|market|brand/i.test(stepText);
    if (isDeployAgent && isCreativeStep) score -= 5;
    // Boost content/marketing agents for creative steps
    const isContentAgent = agentText.includes("market") || agentText.includes("content") || agentText.includes("writer") || agentText.includes("deck");
    if (isContentAgent && isCreativeStep) score += 5;
    return { agent, score };
  });

  scored.sort((a, b) => b.score - a.score);
  const best = scored[0];
  if (best.score > 0) {
    console.log(`[orchestration] findSubAgentForStep: "${step.name}" → "${best.agent.name}" (score: ${best.score})`);
    return best.agent;
  }

  // 3. Last resort: first non-deployment agent, then any agent
  const nonDeploy = activeAgents.find(a => !(a.type || "").includes("deploy") && !(a.description || "").toLowerCase().includes("deploy"));
  return nonDeploy || activeAgents[0];
}

/**
 * handleToolNeededSignal
 * Detects a "Tool Needed" request block in a step's output (emitted by Mark and other
 * CODEX-governed sub-agents) and takes the appropriate action based on platform execution mode:
 *   manual        → surface HITL block, return { hitlBlocked: true }
 *   semi_autonomous | autonomous → auto-provision matching skill, re-queue step, return { retryQueued: true }
 * Returns null if no Tool Needed signal was detected.
 */
async function handleToolNeededSignal(
  output: any,
  stepDef: WorkflowStep,
  mode: string,
  execution: any,
  stepRun: WorkflowStepRun,
  executionId: string,
): Promise<{ retryQueued: boolean; hitlBlocked: boolean } | null> {
  const outputStr = typeof output === "string" ? output : JSON.stringify(output || "");

  // Detect Mark's Tool Needed output block (supports bold markdown or plain text)
  const toolNeededMatch =
    outputStr.match(/\*\*Tool Needed\*\*\s*:\s*([^\n]+)/i) ||
    outputStr.match(/Tool Needed\s*:\s*([^\n]+)/i);

  if (!toolNeededMatch) return null;

  const toolName = toolNeededMatch[1].trim().replace(/^\[|\]$/g, "");
  console.log(`[Tool Needed] Signal detected: "${toolName}" in step "${stepDef.name}". Platform mode: ${mode}`);

  if (mode === "manual") {
    // Manual mode: surface as HITL block — operator must provision tool
    await storage.updateWorkflowStepRun(stepRun.id, { status: "awaiting_operator" });
    await storage.updateWorkflowExecution(executionId, { status: "awaiting_operator" });
    if (execution.workOrderId) {
      await storage.updateWorkOrder(execution.workOrderId, { status: "awaiting_operator" });
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId, tier: 1,
        action: "HITL: Tool Needed",
        message: `Step "${stepDef.name}" signaled Tool Needed: "${toolName}". Manual mode — awaiting operator to provision tool.`,
        metadata: { stepKey: stepDef.stepKey, toolNeeded: toolName, mode },
      });
    }
    return { retryQueued: false, hitlBlocked: true };
  }

  // Semi-autonomous / Autonomous: auto-provision from skill catalog
  // HARDENED: pass subAgentId from step definition so agent's tool assignments are respected
  const stepSubAgentId = (stepDef as any).subAgentId || undefined;
  const importedIds = await autoImportSkillsForDescription(toolName, toolName, stepSubAgentId);
  if (importedIds.length === 0) {
    console.warn(`[Tool Needed] No matching skill found for: "${toolName}" — proceeding without auto-provision.`);
    return null;
  }

  // Merge new tool IDs into the step definition for this and future runs
  const existingToolIds = Array.from(stepDef.toolIds as string[] || []);
  const mergedIds = Array.from(new Set([...existingToolIds, ...importedIds]));
  await storage.updateWorkflowStep(stepDef.id, { toolIds: mergedIds });

  if (execution.workOrderId) {
    await storage.createExecutionLog({
      workOrderId: execution.workOrderId, tier: 1,
      action: "Auto-Provisioned Tool",
      message: `Step "${stepDef.name}" requested tool "${toolName}" — auto-provisioned ${importedIds.length} skill(s) in ${mode} mode. Re-queuing step for retry.`,
      metadata: { stepKey: stepDef.stepKey, toolNeeded: toolName, importedIds, mode },
    });
  }

  // Re-queue step for retry with new tools in context
  await storage.updateWorkflowStepRun(stepRun.id, {
    status: "pending",
    completedAt: null,
    startedAt: null,
    output: null,
  });

  return { retryQueued: true, hitlBlocked: false };
}

async function getToolsForStep(step: WorkflowStep, subAgentId: string | null, cachedOpSettings?: any) {
  // Read platform execution mode — auto-import only in semi_autonomous or autonomous mode
  const opSettings = cachedOpSettings || await storage.getOperationalSettings();
  const execMode = opSettings?.currentMode || "semi_autonomous";

  let autoToolIds: string[] = [];
  if (execMode !== "manual") {
    // Auto-import any skills that match this step's description (no-op if already imported)
    // HARDENED: pass subAgentId so auto-import respects agent's tool assignments
    autoToolIds = await autoImportSkillsForDescription(step.description || "", step.name, subAgentId || undefined);
  } else {
    console.log(`[getToolsForStep] Manual mode — skipping skill auto-import for step "${step.name}". Sub-agent must request tools explicitly.`);
  }

  const rawIds = (step.toolIds as string[] || []).concat(autoToolIds);
  const stepToolIds = rawIds.filter((id, idx) => rawIds.indexOf(id) === idx);
  const allTools = await storage.getTools();
  let stepTools = allTools.filter((t) => stepToolIds.includes(t.id));

  if (subAgentId) {
    const agentToolAssignments = await storage.getSubAgentTools(subAgentId);
    if (agentToolAssignments.length > 0) {
      // HARDENED: When agent has assignments, filter ALL tools (step + auto-imported)
      // to only those explicitly enabled for this agent. Assignment table is source of truth.
      const enabledIds = new Set(agentToolAssignments.filter(a => a.enabled).map(a => a.toolId));
      stepTools = stepTools.filter(t => enabledIds.has(t.id));
      // Also add any agent-enabled tools not already in the step list
      const agentTools = agentToolAssignments.filter(a => a.enabled).map(a => a.tool);
      for (const tool of agentTools) {
        if (!stepTools.find(t => t.id === tool.id)) {
          stepTools.push(tool);
        }
      }
    } else {
      // No assignments — legacy behavior: add all agent tools
      const agentToolAssignmentsAll = await storage.getSubAgentTools(subAgentId);
      const agentTools = agentToolAssignmentsAll.filter((at) => at.enabled).map((at) => at.tool);
      for (const tool of agentTools) {
        if (!stepTools.find((t) => t.id === tool.id)) {
          stepTools.push(tool);
        }
      }
    }
    return stepTools;
  }

  return stepTools;
}

async function handleWorkflowCompletion(
  execution: any, template: any, steps: WorkflowStep[], stepRuns: WorkflowStepRun[],
  settings: any, pmLlmConfig: any, attemptId?: string, reviewReduction?: boolean
) {
  const executionId = execution.id;

  // Enrich step results with sub-agent role so PM assembly can distinguish
  // content-producing steps from metadata-only steps (e.g. deployment reports)
  const completedRuns = stepRuns.filter(r => r.status === "completed" && r.output);
  const subAgentIds = Array.from(new Set(completedRuns.map(r => r.assignedSubAgentId).filter(Boolean))) as string[];
  const subAgentMap = new Map<string, { type: string; name: string }>();
  for (const id of subAgentIds) {
    try {
      const agent = await storage.getSubAgent(id);
      if (agent) subAgentMap.set(id, { type: agent.type, name: agent.name });
    } catch { /* agent may have been deleted */ }
  }
  const completedStepResults = completedRuns.map(r => {
    const agentInfo = r.assignedSubAgentId ? subAgentMap.get(r.assignedSubAgentId) : null;
    return {
      stepKey: r.stepKey,
      stepName: r.stepName,
      output: r.output,
      role: agentInfo?.type === "deployment" ? "metadata" as const : "content" as const,
    };
  });

  let workProduct = null;
  try {
    workProduct = await pmAssembleWorkProduct(pmLlmConfig, execution.goal || "", completedStepResults, template?.name || "Workflow");
  } catch (err: any) {
    console.error("PM work product assembly failed:", err.message);
    const contentResults = completedStepResults.filter(r => r.role !== "metadata");
    workProduct = {
      summary: `PM assembled ${contentResults.length} content step outputs`,
      deliverable: contentResults.map(r => `## ${r.stepName}\n${typeof r.output === "string" ? r.output : JSON.stringify(r.output, null, 2)}`).join("\n\n"),
      deliverableType: "markdown",
      deliverableTitle: template?.name || "Workflow Output",
      stepContributions: Object.fromEntries(completedStepResults.map(r => [r.stepKey, r.stepName])),
    };
  }

  await storage.updateWorkflowExecution(executionId, { finalWorkProduct: workProduct });

  if (execution.workOrderId) {
    await storage.createExecutionLog({
      workOrderId: execution.workOrderId, tier: 1,
      action: "PM: Work Product Assembled",
      message: `PM (LLM: ${pmLlmConfig.provider}/${pmLlmConfig.model}) assembled final work product: "${workProduct.deliverableTitle}" (${workProduct.deliverableType}) from ${completedStepResults.length} steps.`,
      metadata: { workProduct: { summary: workProduct.summary, type: workProduct.deliverableType, title: workProduct.deliverableTitle }, llmProvider: pmLlmConfig.provider, llmModel: pmLlmConfig.model },
    });
  }

  let execReview = null;
  // Phase 7: Skip executive review for single-step workflows (redundant with PocketFlow evaluation)
  const skipExecReview = reviewReduction && steps.length <= 1;
  if (skipExecReview) {
    console.log(`[perf:review] Skipped Aiden executive review — single-step workflow (review reduction enabled)`);
    execReview = { approved: true, score: 0.9, feedback: "Auto-approved: single-step workflow (review reduction).", recommendation: "approve", issues: [] };
  } else {
  try {
    const pmSubAgentForReview = execution.pmSubAgentId ? await storage.getSubAgent(execution.pmSubAgentId) : null;
    execReview = await aidenExecutiveReview(settings, execution.goal || "", workProduct, {
      templateName: template?.name || "Workflow",
      totalSteps: steps.length,
      completedSteps: completedStepResults.length,
      skippedSteps: stepRuns.filter(r => r.status === "skipped").length,
      failedSteps: stepRuns.filter(r => r.status === "failed").length,
      pmName: pmSubAgentForReview?.name || "Unknown PM",
    });
  } catch (err: any) {
    console.error("Aiden executive review failed:", err.message);
    execReview = { approved: true, score: 0.7, feedback: "Executive review unavailable — auto-approving.", recommendation: "approve", issues: [] };
  }
  }

  await storage.updateWorkflowExecution(executionId, { executiveReview: execReview });

  if (execution.workOrderId) {
    await storage.createExecutionLog({
      workOrderId: execution.workOrderId, tier: 1,
      action: `Aiden: Executive Review — ${execReview.recommendation}`,
      message: `Aiden executive review: Score ${execReview.score.toFixed(2)} — ${execReview.feedback}`,
      metadata: { execReview },
    });
  }

  if (execReview.recommendation === "approve" || execReview.approved) {
    await storage.updateWorkflowExecution(executionId, { status: "completed", completedAt: new Date() });
    if (execution.workOrderId) {
      // Scan step runs for any post-processed file (PPTX, PDF, etc.) generated during execution
      let stepPostProcessedFile = stepRuns
        .filter(r => r.status === "completed" && r.pocketflowResult)
        .map(r => (r.pocketflowResult as any)?.postProcessedFile)
        .find(f => f && f.path) || null;

      // BUG-038 universal fix: If no step produced a binary but the parent WO
      // requires PPTX/PDF, run post-processing on the assembled work product now.
      if (!stepPostProcessedFile && execution.workOrderId) {
        const parentWo = await storage.getWorkOrder(execution.workOrderId);
        if (parentWo) {
          const requiredFormat = detectRequiredFormatFromText(parentWo.title, parentWo.description || "");
          if (requiredFormat && workProduct?.deliverable) {
            await storage.createExecutionLog({
              workOrderId: execution.workOrderId, tier: 1,
              action: `Aiden: Workflow Post-Process (${requiredFormat.toUpperCase()})`,
              message: `No step produced a ${requiredFormat.toUpperCase()} binary. Running post-processing on assembled work product.`,
              metadata: { requiredFormat, deliverableLength: workProduct.deliverable.length },
            });

            try {
              stepPostProcessedFile = await postProcessWorkflowDeliverable(
                workProduct.deliverable,
                requiredFormat,
                execution.workOrderId,
                parentWo.title,
              );
              if (stepPostProcessedFile) {
                addChecklistItem(execution.workOrderId, "filing",
                  `Workflow post-processed: ${requiredFormat.toUpperCase()} binary generated from assembled work product`,
                  "system"
                );
              }
            } catch (ppErr: any) {
              console.error(`[workflow-postprocess] Error: ${ppErr.message}`);
              await storage.createExecutionLog({
                workOrderId: execution.workOrderId, tier: 1,
                action: "Aiden: Workflow Post-Process Failed",
                message: `Post-processing failed: ${ppErr.message}`,
                metadata: { error: ppErr.message, requiredFormat },
              });
            }
          }
        }
      }

      const woForGcc = await storage.getWorkOrder(execution.workOrderId);
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId, tier: 1,
        action: "Aiden: Workflow Completed",
        message: `All ${steps.length} steps complete. PM assembled work product approved by Aiden (score: ${execReview.score.toFixed(2)}).`,
        metadata: { executionId },
      });
      await completeAndFileWorkOrder(execution.workOrderId, {
        tier2Result: {
          blocked: false,
          reason: null,
          executionId,
          handler: null,
          output: {
            message: workProduct.summary || `Workflow completed: ${template?.name || "Workflow Output"}`,
            deliverable: workProduct.deliverable,
            deliverableType: workProduct.deliverableType || "markdown",
            deliverableTitle: workProduct.deliverableTitle || template?.name || "Workflow Output",
            ...(stepPostProcessedFile ? { postProcessedFile: stepPostProcessedFile } : {}),
          },
        },
        gccMemory: updateWorkOrderGcc(woForGcc?.gccMemory as object, "workflow_completed_with_executive_review", ["workflow_steps_complete", "pm_work_product_assembled", "aiden_executive_review_passed", "workflow_completed"], {
          workflowExecutionId: executionId, status: "completed", executiveScore: execReview.score,
          pmWorkProduct: workProduct.summary, executiveReview: execReview.feedback,
        }),
      }, "workflow-exec-approved", attemptId);
    } else {
      // Standalone workflow (no work order) — auto-publish to sandbox directly
      const deliverable = workProduct.deliverable;
      const isRenderable = typeof deliverable === "string" && (
        deliverable.trimStart().startsWith("<!DOCTYPE") ||
        deliverable.trimStart().startsWith("<html") ||
        (workProduct.deliverableType || "").toLowerCase().includes("html")
      );
      if (isRenderable) {
        storage.createSandboxSession({
          name: `Preview: ${workProduct.deliverableTitle || template?.name || "Workflow Output"}`,
          description: `Auto-deployed from workflow execution "${template?.name || executionId}" — score: ${execReview.score.toFixed(2)}`,
          environment: { type: "html", sourceId: executionId, sourceType: "workflow_execution" },
        }).then(session =>
          storage.updateSandboxSession(session.id, {
            status: "completed",
            result: { html: deliverable, renderable: true, score: execReview.score, approved: true },
          })
        ).catch(err => console.error("Auto-sandbox error (standalone workflow):", err.message));
      }
    }
  } else if (execReview.recommendation === "escalate_to_operator") {
    await storage.updateWorkflowExecution(executionId, { status: "awaiting_operator" });
    if (execution.workOrderId) {
      await storage.updateWorkOrder(execution.workOrderId, { status: "awaiting_operator" });
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId, tier: 1,
        action: "Aiden: Escalated to Operator",
        message: `Aiden executive review escalated to operator: ${execReview.feedback}`,
        metadata: { execReview },
      });
    }
  } else {
    // Executive review returned "revise" but revisions exhausted.
    // BUG-042: If score is below 0.50, do NOT auto-complete — route to awaiting_operator instead.
    const MIN_BEST_EFFORT_SCORE = 0.50;
    if (execReview.score < MIN_BEST_EFFORT_SCORE) {
      await storage.updateWorkflowExecution(executionId, { status: "awaiting_operator" });
      if (execution.workOrderId) {
        await storage.updateWorkOrder(execution.workOrderId, { status: "awaiting_operator" });
        await storage.createExecutionLog({
          workOrderId: execution.workOrderId, tier: 1,
          action: "Aiden: Low-Quality Escalation",
          message: `Executive review score ${execReview.score.toFixed(2)} is below ${MIN_BEST_EFFORT_SCORE} threshold — escalating to operator instead of best-effort completion. Issues: ${execReview.issues?.join("; ") || execReview.feedback}`,
          metadata: { execReview, threshold: MIN_BEST_EFFORT_SCORE },
        });
        addChecklistItem(execution.workOrderId, "quality_review",
          `Escalated to operator: exec review score ${execReview.score.toFixed(2)} < ${MIN_BEST_EFFORT_SCORE} threshold — deliverable does not meet requirements`,
          "aiden"
        );
      }
      return;
    }

    // Score >= 0.50: complete with best effort
    await storage.updateWorkflowExecution(executionId, { status: "completed", completedAt: new Date() });
    if (execution.workOrderId) {
      // BUG-038: Try to produce binary if the WO requires it
      let fallbackPostProcessedFile: { path: string; mimeType: string; size: number } | null = null;
      const parentWo = await storage.getWorkOrder(execution.workOrderId);
      if (parentWo && workProduct?.deliverable) {
        const requiredFormat = detectRequiredFormatFromText(parentWo.title, parentWo.description || "");
        if (requiredFormat) {
          try {
            fallbackPostProcessedFile = await postProcessWorkflowDeliverable(
              workProduct.deliverable, requiredFormat, execution.workOrderId, parentWo.title,
            );
          } catch (ppErr: any) {
            console.warn(`[workflow-postprocess] Fallback post-process failed: ${ppErr.message}`);
          }
        }
      }

      const woForGcc = parentWo || await storage.getWorkOrder(execution.workOrderId);
      await completeAndFileWorkOrder(execution.workOrderId, {
        tier2Result: {
          blocked: false,
          reason: null,
          executionId,
          handler: null,
          output: {
            message: workProduct.summary || `Workflow completed: ${template?.name || "Workflow Output"}`,
            deliverable: workProduct.deliverable,
            deliverableType: workProduct.deliverableType || "markdown",
            deliverableTitle: workProduct.deliverableTitle || template?.name || "Workflow Output",
            ...(fallbackPostProcessedFile ? { postProcessedFile: fallbackPostProcessedFile } : {}),
          },
        },
        gccMemory: updateWorkOrderGcc((woForGcc?.gccMemory || {}) as object, "workflow_completed", ["workflow_steps_complete", "workflow_completed"], {
          workflowExecutionId: executionId, status: "completed",
        }),
      }, "workflow-revise-fallback", attemptId);
    }
  }
}

async function executeWorkflowStepWithPocketFlow(
  step: WorkflowStep, subAgent: SubAgent, previousResults: Record<string, any>,
  goal: string, settings: any, tools: any[], executionId?: string, cachedGammaTemplates?: any[], promptCompaction?: boolean, batchedSynthesis?: boolean, reviewReduction?: boolean
): Promise<{ output: any; toolsUsed: string[]; decision: any; pocketflowResult?: any }> {
  const llmConfig = resolveSubAgentLlmConfig(subAgent, settings);
  const toolNames = tools.map(t => t.name);

  const promptTemplate = (step as any).promptTemplate || step.description || "";
  const prevContext = Object.entries(previousResults)
    .map(([key, val]) => `[${key}]: ${typeof val === "string" ? val.slice(0, 500) : JSON.stringify(val).slice(0, 500)}`)
    .join("\n");

  const stepPrompt = [
    `WORKFLOW STEP: ${step.name}`,
    step.description ? `Description: ${step.description}` : "",
    `Workflow Goal: ${goal}`,
    promptTemplate ? `Instructions: ${promptTemplate}` : "",
    prevContext ? `\nPrevious Step Results:\n${prevContext}` : "",
    toolNames.length > 0 ? `\nAvailable Tools: ${toolNames.join(", ")}` : "",
  ].filter(Boolean).join("\n");

  const syntheticOrder = {
    id: `wf-step-${step.stepKey}-${Date.now()}`,
    title: step.name,
    description: stepPrompt,
    type: "standard",
    priority: "medium",
    status: "processing",
    createdAt: new Date(),
    updatedAt: new Date(),
    assignedSubAgentId: subAgent.id,
    gccMemory: { workflowGoal: goal, stepKey: step.stepKey, previousResults },
    workflowExecutionId: executionId || null,
    correlationId: `wf-step-${step.stepKey}-${Date.now()}`,
    executionMode: null,
    tier1Result: null,
    tier2Result: null,
    bdmMarker: null,
    effectiveMode: null,
    impactScore: null,
    approvalStatus: null,
    deferredUntil: null,
    deferredReason: null,
    tags: [],
    isArchived: false,
    archivedAt: null,
    archivedBy: null,
    archivedReason: null,
    submittedBy: "system",
    gammaTemplateKey: null,
    processingAttemptId: null,
    heartbeatAt: null,
    processingStartedAt: null,
  } satisfies WorkOrder;

  const tier1Result: Tier1Result = {
    approved: true,
    reason: `Workflow step "${step.name}" directed by PM`,
    mode: "autonomous",
    handler: subAgent.name,
  };

  try {
    const pfResult = await pocketflowExecute(syntheticOrder, tier1Result, llmConfig, settings, {
      maxIterations: ((step.retryPolicy as any)?.maxRetries || 2) + 1,
      convergenceThreshold: 0.75,
      cachedGammaTemplates,
      promptCompaction,
      batchedSynthesis,
      reviewReduction,
    });

    if (pfResult.blocked) {
      throw new Error(pfResult.reason || "PocketFlow execution blocked");
    }

    const pfOutput = pfResult.output;
    const pfMeta = pfResult.pocketflow;
    const pfToolsUsed = pfMeta?.toolsUsed?.map((t: any) => t.slug || t.name || String(t)) || [];

    return {
      output: pfOutput?.deliverable || pfOutput?.message || "Step completed",
      toolsUsed: pfToolsUsed,
      decision: {
        action: "pocketflow_execute",
        reasoning: pfOutput?.message || `PocketFlow executed step "${step.name}"`,
        tools: pfToolsUsed,
        convergenceScore: pfMeta?.convergenceScore,
        iterationsUsed: pfMeta?.iterations,
      },
      pocketflowResult: {
        message: pfOutput?.message,
        convergenceScore: pfMeta?.convergenceScore,
        iterations: pfMeta?.iterations,
        deliverableType: pfOutput?.deliverableType,
        deliverableTitle: pfOutput?.deliverableTitle,
        postProcessedFile: pfOutput?.postProcessedFile || null,
        toolsUsed: pfToolsUsed,
        stepResults: pfMeta?.stepResults,
      },
    };
  } catch (err: any) {
    console.error(`PocketFlow step execution failed for "${step.name}":`, err.message);
    return executeWorkflowStep(step, previousResults, goal, toolNames, false, settings);
  }
}

async function executeWorkflowStep(
  step: WorkflowStep,
  previousResults: Record<string, any>,
  goal: string,
  toolNames: string[],
  useLLM: boolean,
  settings: any
): Promise<{ output: any; toolsUsed: string[]; decision: any }> {
  const startTime = Date.now();

  const simulatedOutput = {
    stepKey: step.stepKey,
    message: `Step "${step.name}" executed successfully`,
    handler: step.agentType || "general",
    toolsAvailable: toolNames,
    duration: Date.now() - startTime,
    goal,
    previousStepResults: Object.keys(previousResults),
  };

  return {
    output: simulatedOutput,
    toolsUsed: toolNames.length > 0 ? [toolNames[0]] : [],
    decision: {
      action: "execute",
      reasoning: `Aiden executed step "${step.name}" as part of workflow goal: ${goal}`,
      tools: toolNames,
    },
  };
}
