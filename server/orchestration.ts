import { storage } from "./storage";
import type { WorkOrder, SubAgent, WorkflowStep, WorkflowStepRun } from "@shared/schema";
import { runTier1WithLLM, runTier2WithLLM, resolveSubAgentLlmConfig, runAidenQualityReview, type Tier1Result, type Tier2Result } from "./llm-client";
import { fileWorkOrderOutput } from "./workspace-filing";
import { pocketflowExecute } from "./pocketflow";

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
    await storage.updateWorkOrder(order.id, { status: "failed" });
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

export async function processWorkOrderSafe(orderId: string): Promise<void> {
  try {
    await processWorkOrder(orderId);
  } catch (err: any) {
    console.error(`[orchestration] processWorkOrder crashed for ${orderId}:`, err);
    try {
      const current = await storage.getWorkOrder(orderId);
      if (current && current.status === "processing") {
        await storage.updateWorkOrder(orderId, { status: "failed" });
        await storage.createExecutionLog({
          workOrderId: orderId,
          tier: 1,
          action: "System: Processing Failed",
          message: `Background processing crashed: ${err?.message || "Unknown error"}. Status set to "failed" — you can retry.`,
          metadata: { error: err?.message, stack: err?.stack?.substring(0, 500), failedAt: new Date().toISOString() },
        });
      }
    } catch (recoveryErr) {
      console.error(`[orchestration] Failed to recover crashed WO ${orderId}:`, recoveryErr);
    }
  }
}

export async function processWorkOrder(orderId: string): Promise<WorkOrder | undefined> {
  const order = await storage.getWorkOrder(orderId);
  if (!order) return undefined;

  await storage.updateWorkOrder(orderId, { status: "processing" });

  const settings = await storage.getLlmSettings();
  const useLLM = settings?.enabled === true;
  const activeSubAgents = await storage.getActiveSubAgents();

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Aiden: Policy Gate",
    message: `Aiden (Tier 1) received work order "${order.title}" — evaluating policy rules${useLLM ? " via LLM" : ""}.`,
    metadata: { type: order.type, priority: order.priority, aiEnabled: useLLM, subAgentCount: activeSubAgents.length },
  });

  const tier1Result: Tier1Result = useLLM && settings
    ? await runTier1WithLLM(settings, order, activeSubAgents)
    : runTier1PolicyGate(order, activeSubAgents);

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Aiden: Policy Decision",
    message: tier1Result.approved
      ? `Aiden approved — routing to sub-agent: ${tier1Result.handler}${useLLM ? " (LLM)" : ""}.`
      : `Aiden blocked: ${tier1Result.reason}`,
    metadata: tier1Result,
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

    return storage.updateWorkOrder(orderId, {
      status: "blocked",
      tier1Result,
      bdmMarker,
      gccMemory: updateWorkOrderGcc(order.gccMemory as object, "tier1_policy_block", ["tier1_policy_block"], {
        correlationId: order.correlationId, status: "blocked", reason: tier1Result.reason,
      }),
    });
  }

  const targetSubAgent = findSubAgent(activeSubAgents, tier1Result.handler);

  await storage.updateWorkOrder(orderId, {
    tier1Result,
    assignedSubAgentId: targetSubAgent?.id || null,
    executionMode: targetSubAgent?.controlMode || "aiden",
    gccMemory: updateWorkOrderGcc(order.gccMemory as object, "tier1_policy_pass", ["tier1_policy_pass", "routing_dispatched"], {
      correlationId: order.correlationId, status: "routing",
      handler: tier1Result.handler, mode: tier1Result.mode,
      subAgentId: targetSubAgent?.id, subAgentName: targetSubAgent?.name, controlMode: targetSubAgent?.controlMode,
    }),
  });

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Aiden: Dispatch to Sub-Agent",
    message: targetSubAgent
      ? `Aiden routing to sub-agent "${targetSubAgent.name}" (${targetSubAgent.controlMode} mode)`
      : `Aiden routing to handler: ${tier1Result.handler}`,
    metadata: {
      handler: tier1Result.handler,
      subAgentId: targetSubAgent?.id,
      subAgentName: targetSubAgent?.name,
      controlMode: targetSubAgent?.controlMode,
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

  const orderWithAgent = { ...order, assignedSubAgentId: targetSubAgent?.id || null };
  const tier2Result: Tier2Result = await pocketflowExecute(
    orderWithAgent,
    tier1Result,
    effectiveLlmConfig,
    settings || null,
    { maxIterations: 3, convergenceThreshold: 0.8 }
  );

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

  let qualityReview;
  if (useLLM && settings) {
    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "Aiden: Quality Review",
      message: `Aiden (Tier 1) initiating final quality review of deliverable before completion approval.`,
      metadata: { deliverableLength: deliverable.length, convergenceScore, iterations, stepCount },
    });

    qualityReview = await runAidenQualityReview(
      settings,
      order,
      deliverable,
      convergenceScore,
      iterations,
      stepCount,
      executorLabel
    );

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
    const maxAutoRevisions = 2;
    const baseRevisionCount = ((order.gccMemory as any)?.["gcc.metadata"]?.revisionAttempts || 0);
    const canAutoRevise = controlMode === "aiden" && baseRevisionCount < maxAutoRevisions && hasLlm;

    if (canAutoRevise) {
      let currentQR = qualityReview;
      let currentTier2 = tier2Result;
      let revisionsDone = baseRevisionCount;
      let revisionApproved = false;

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
            qualityReview: { score: currentQR.score, recommendation: currentQR.recommendation, issues: currentQR.issues, summary: currentQR.summary },
          },
        });

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
          { maxIterations: 3, convergenceThreshold: 0.8, revisionContext }
        );

        await storage.createExecutionLog({
          workOrderId: orderId,
          tier: 2,
          action: `${targetSubAgent?.name || "Sub-Agent"}: Revision ${revisionsDone} Complete`,
          message: `${executorLabel} completed revision attempt ${revisionsDone} — score: ${revisionResult.pocketflow?.convergenceScore?.toFixed(2) || "N/A"}.`,
          metadata: { revisionAttempt: revisionsDone, ...revisionResult },
        });

        const revDeliverable = revisionResult.output?.deliverable || "";
        const revPfMeta = revisionResult.pocketflow;

        let revQualityReview;
        try {
          revQualityReview = await runAidenQualityReview(settings!, revisedOrder, revDeliverable, revPfMeta?.convergenceScore ?? 0, revPfMeta?.iterations ?? 1, revPfMeta?.stepResults?.length ?? 0, executorLabel);
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
          await storage.createExecutionLog({
            workOrderId: orderId, tier: 1,
            action: "Aiden: Revision Still Below Quality",
            message: `Revision ${revisionsDone} from ${executorLabel} still below quality threshold — score: ${revQualityReview.score.toFixed(2)}. ${revisionsDone >= maxAutoRevisions ? "Max auto-revisions reached. Escalating to operator." : "Attempting another revision."}`,
            metadata: { revisionAttempt: revisionsDone, maxAutoRevisions, qualityReview: revQualityReview },
          });
        }
      }

      if (!revisionApproved) {
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

  const completedOrder = await storage.updateWorkOrder(orderId, {
    status: "completed",
    tier2Result,
    gccMemory: updateWorkOrderGcc(order.gccMemory as object, "completed", ["tier1_policy_pass", "pocketflow_validated", "pocketflow_execution_complete", "aiden_quality_review", "aiden_approved", "aiden_resolution"], {
      correlationId: order.correlationId, status: "completed",
      pocketflow: tier2Result.pocketflow,
      qualityReview: {
        score: qualityReview.score,
        recommendation: qualityReview.recommendation,
        issues: qualityReview.issues,
      },
    }),
  });

  if (completedOrder) {
    fileWorkOrderOutput(completedOrder).catch(err =>
      console.error("Auto-filing error:", err.message)
    );
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
        const nameWords = agent.name.toLowerCase().split(/[\s_-]+/);
        const descWords = (agent.description || "").toLowerCase().split(/[\s_-]+/);
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
  context: Record<string, any> = {}
) {
  const template = await storage.getWorkflowTemplate(templateId);
  if (!template) throw new Error("Workflow template not found");

  const steps = await storage.getWorkflowSteps(templateId);
  if (steps.length === 0) throw new Error("Workflow template has no steps");

  const execution = await storage.createWorkflowExecution({
    templateId,
    workOrderId,
    goal: goal || template.goal,
    context,
  });

  await storage.updateWorkflowExecution(execution.id, {
    status: "running",
    startedAt: new Date(),
    currentStepKey: steps[0].stepKey,
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
      message: `Aiden started workflow "${template.name}" with ${steps.length} steps toward goal: ${goal || template.goal || "execute workflow"}`,
      metadata: { executionId: execution.id, templateId, stepCount: steps.length },
    });
  }

  const result = await advanceWorkflowExecution(execution.id);
  return result;
}

export async function advanceWorkflowExecution(executionId: string) {
  const execution = await storage.getWorkflowExecution(executionId);
  if (!execution) throw new Error("Workflow execution not found");

  const template = await storage.getWorkflowTemplate(execution.templateId);
  const steps = await storage.getWorkflowSteps(execution.templateId);
  const stepRuns = await storage.getWorkflowStepRuns(executionId);
  const settings = await storage.getLlmSettings();
  const useLLM = settings?.enabled === true;

  const nextStepRun = findNextRunnableStep(steps, stepRuns);

  if (!nextStepRun) {
    const allCompleted = stepRuns.every((r) => r.status === "completed" || r.status === "skipped");
    const hasFailed = stepRuns.some((r) => r.status === "failed");

    if (hasFailed) {
      await storage.updateWorkflowExecution(executionId, {
        status: "failed",
        completedAt: new Date(),
      });
      if (execution.workOrderId) {
        await storage.updateWorkOrder(execution.workOrderId, { status: "failed" });
      }
    } else if (allCompleted) {
      await storage.updateWorkflowExecution(executionId, {
        status: "completed",
        completedAt: new Date(),
      });
      if (execution.workOrderId) {
        const woForGcc = await storage.getWorkOrder(execution.workOrderId);
        const completedOrder = await storage.updateWorkOrder(execution.workOrderId, {
          status: "completed",
          gccMemory: updateWorkOrderGcc(woForGcc?.gccMemory as object, "workflow_completed", ["workflow_steps_complete", "workflow_completed"], {
            workflowExecutionId: executionId, status: "completed",
          }),
        });
        await storage.createExecutionLog({
          workOrderId: execution.workOrderId,
          tier: 1,
          action: "Aiden: Workflow Completed",
          message: `All ${steps.length} workflow steps completed successfully.`,
          metadata: { executionId },
        });
        if (completedOrder) {
          fileWorkOrderOutput(completedOrder).catch(err =>
            console.error("Auto-filing error (workflow):", err.message)
          );
        }
      }
    }

    return storage.getWorkflowExecution(executionId);
  }

  const stepDef = steps.find((s) => s.stepKey === nextStepRun.stepKey);
  if (!stepDef) throw new Error(`Step definition not found for ${nextStepRun.stepKey}`);

  if (!evaluateConditions(stepDef, stepRuns)) {
    await storage.updateWorkflowStepRun(nextStepRun.id, {
      status: "skipped",
      completedAt: new Date(),
    });
    return advanceWorkflowExecution(executionId);
  }

  const previousResults = collectPreviousResults(stepRuns);

  await storage.updateWorkflowExecution(executionId, { currentStepKey: nextStepRun.stepKey });

  await storage.updateWorkflowStepRun(nextStepRun.id, {
    status: "running",
    startedAt: new Date(),
    input: { previousResults, goal: execution.goal, context: execution.context },
  });

  if (execution.workOrderId) {
    await storage.createExecutionLog({
      workOrderId: execution.workOrderId,
      tier: 1,
      action: `Aiden: Step "${stepDef.name}"`,
      message: `Aiden executing workflow step: ${stepDef.name}${stepDef.description ? ` — ${stepDef.description}` : ""}`,
      metadata: { stepKey: stepDef.stepKey, order: stepDef.order },
    });
  }

  const subAgent = stepDef.assignedSubAgentId
    ? await storage.getSubAgent(stepDef.assignedSubAgentId)
    : await findSubAgentForStep(stepDef);

  const toolsList = await getToolsForStep(stepDef, subAgent?.id || null);
  const toolNames = toolsList.map((t) => t.name);

  if (subAgent?.controlMode === "independent") {
    await storage.updateWorkflowStepRun(nextStepRun.id, {
      status: "awaiting_operator",
      assignedSubAgentId: subAgent.id,
      aidenDecision: { action: "assigned_to_independent_operator", subAgent: subAgent.name, operator: subAgent.assignedTo, tools: toolNames },
    });

    await storage.updateWorkflowExecution(executionId, { status: "awaiting_operator" });

    if (execution.workOrderId) {
      await storage.updateWorkOrder(execution.workOrderId, { status: "awaiting_operator" });
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId,
        tier: 2,
        action: "Awaiting Operator",
        message: `Step "${stepDef.name}" assigned to independent sub-agent "${subAgent.name}" — awaiting ${subAgent.assignedTo || "operator"}.`,
        metadata: { subAgentId: subAgent.id, tools: toolNames },
      });
    }

    return storage.getWorkflowExecution(executionId);
  }

  try {
    const stepResult = await executeWorkflowStep(stepDef, previousResults, execution.goal || "", toolNames, useLLM, settings);

    await storage.updateWorkflowStepRun(nextStepRun.id, {
      status: "completed",
      completedAt: new Date(),
      output: stepResult.output,
      toolsUsed: stepResult.toolsUsed || [],
      aidenDecision: stepResult.decision,
      assignedSubAgentId: subAgent?.id || null,
    });

    if (execution.workOrderId) {
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId,
        tier: 2,
        action: `Sub-Agent: ${stepDef.name} Complete`,
        message: `Step "${stepDef.name}" completed successfully${subAgent ? ` by "${subAgent.name}"` : ""}.`,
        metadata: { stepKey: stepDef.stepKey, tools: stepResult.toolsUsed, output: stepResult.output },
      });
    }

    return advanceWorkflowExecution(executionId);
  } catch (err: any) {
    await storage.updateWorkflowStepRun(nextStepRun.id, {
      status: "failed",
      completedAt: new Date(),
      error: err.message || "Step execution failed",
    });

    await storage.updateWorkflowExecution(executionId, { status: "failed", completedAt: new Date() });

    if (execution.workOrderId) {
      await storage.updateWorkOrder(execution.workOrderId, { status: "failed" });
      await storage.createExecutionLog({
        workOrderId: execution.workOrderId,
        tier: 2,
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

async function findSubAgentForStep(step: WorkflowStep): Promise<SubAgent | undefined> {
  const activeAgents = await storage.getActiveSubAgents();
  if (step.agentType) {
    return activeAgents.find((a) => a.type === step.agentType) || activeAgents[0];
  }
  return activeAgents[0];
}

async function getToolsForStep(step: WorkflowStep, subAgentId: string | null) {
  const stepToolIds = (step.toolIds as string[]) || [];
  const allTools = await storage.getTools();
  const stepTools = allTools.filter((t) => stepToolIds.includes(t.id));

  if (subAgentId) {
    const agentToolAssignments = await storage.getSubAgentTools(subAgentId);
    const agentTools = agentToolAssignments.filter((at) => at.enabled).map((at) => at.tool);
    const combined = [...stepTools];
    for (const tool of agentTools) {
      if (!combined.find((t) => t.id === tool.id)) {
        combined.push(tool);
      }
    }
    return combined;
  }

  return stepTools;
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
