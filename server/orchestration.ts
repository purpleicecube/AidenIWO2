import { storage } from "./storage";
import type { WorkOrder, SubAgent } from "@shared/schema";
import { runTier1WithLLM, runTier2WithLLM, type Tier1Result, type Tier2Result } from "./llm-client";

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
      gccMemory: {
        ...((order.gccMemory as object) || {}),
        lastAction: "tier1_policy_block",
        correlationId: order.correlationId,
        blockedAt: new Date().toISOString(),
      },
    });
  }

  const targetSubAgent = findSubAgent(activeSubAgents, tier1Result.handler);

  await storage.updateWorkOrder(orderId, {
    tier1Result,
    assignedSubAgentId: targetSubAgent?.id || null,
    executionMode: targetSubAgent?.controlMode || "aiden",
    gccMemory: {
      ...((order.gccMemory as object) || {}),
      routingContext: {
        handler: tier1Result.handler,
        mode: tier1Result.mode,
        subAgentId: targetSubAgent?.id,
        subAgentName: targetSubAgent?.name,
        controlMode: targetSubAgent?.controlMode,
      },
      correlationId: order.correlationId,
      tier1CompletedAt: new Date().toISOString(),
    },
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
      gccMemory: {
        ...((order.gccMemory as object) || {}),
        lastAction: "awaiting_independent_operator",
        correlationId: order.correlationId,
        assignedSubAgent: targetSubAgent.name,
        assignedTo: targetSubAgent.assignedTo,
        breadcrumbs: ["tier1_policy_pass", "dispatched_to_independent_sub_agent"],
      },
    });
  }

  const tier2Result: Tier2Result = useLLM && settings
    ? await runTier2WithLLM(settings, order, tier1Result)
    : runTier2Execution(order, tier1Result);

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 2,
    action: "Sub-Agent: Schema Validation",
    message: `Sub-agent${targetSubAgent ? ` "${targetSubAgent.name}"` : ""} validated work order schema${useLLM ? " via Aiden" : ""}.`,
    metadata: { valid: true, subAgentName: targetSubAgent?.name },
  });

  if (tier2Result.blocked) {
    const bdmMarker = {
      type: "execution_block",
      reason: tier2Result.reason,
      tier: 2,
      timestamp: new Date().toISOString(),
      subAgentId: targetSubAgent?.id,
      subAgentName: targetSubAgent?.name,
    };

    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 2,
      action: "BDM Marker Emitted",
      message: `Sub-agent${targetSubAgent ? ` "${targetSubAgent.name}"` : ""} blocked execution: ${tier2Result.reason}`,
      metadata: bdmMarker,
    });

    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "Aiden: BDM Resolution",
      message: "Aiden received BDM marker from sub-agent — pausing for human decision.",
      metadata: { bdmMarker },
    });

    return storage.updateWorkOrder(orderId, {
      status: "blocked",
      tier2Result,
      bdmMarker,
      gccMemory: {
        ...((order.gccMemory as object) || {}),
        lastAction: "tier2_execution_block",
        correlationId: order.correlationId,
        blockedAt: new Date().toISOString(),
        breadcrumbs: ["tier1_policy_pass", "tier2_schema_valid", "tier2_execution_block"],
      },
    });
  }

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 2,
    action: "Sub-Agent: Execution Complete",
    message: `Sub-agent${targetSubAgent ? ` "${targetSubAgent.name}"` : ""} executed work order successfully${useLLM ? " (Aiden-controlled)" : ""}.`,
    metadata: tier2Result,
  });

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Aiden: Resolution",
    message: "Aiden confirmed successful execution — work order completed.",
    metadata: { finalStatus: "completed" },
  });

  return storage.updateWorkOrder(orderId, {
    status: "completed",
    tier2Result,
    gccMemory: {
      ...((order.gccMemory as object) || {}),
      lastAction: "completed",
      correlationId: order.correlationId,
      completedAt: new Date().toISOString(),
      breadcrumbs: ["tier1_policy_pass", "tier2_schema_valid", "tier2_execution_complete", "aiden_resolution"],
    },
  });
}

function findSubAgent(agents: SubAgent[], handler: string | null): SubAgent | undefined {
  if (!handler || agents.length === 0) return undefined;

  const typeMap: Record<string, string> = {
    deploy_executor: "deployment",
    maintenance_executor: "maintenance",
    incident_executor: "incident",
    change_executor: "change_request",
    security_executor: "security",
    general_executor: "general",
  };

  const targetType = typeMap[handler] || "general";
  return agents.find((a) => a.type === targetType) || agents.find((a) => a.type === "general") || agents[0];
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

  return {
    blocked: false,
    reason: null,
    executionId: `exec_${Date.now()}`,
    handler: tier1Result.handler,
    output: {
      message: `Work order "${order.title}" processed successfully.`,
    },
  };
}
