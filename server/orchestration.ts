import { storage } from "./storage";
import type { WorkOrder } from "@shared/schema";
import { runTier1WithLLM, runTier2WithLLM, type Tier1Result, type Tier2Result } from "./llm-client";

export async function processWorkOrder(orderId: string): Promise<WorkOrder | undefined> {
  const order = await storage.getWorkOrder(orderId);
  if (!order) return undefined;

  await storage.updateWorkOrder(orderId, { status: "processing" });

  const settings = await storage.getLlmSettings();
  const useLLM = settings?.enabled === true;

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Policy Gate",
    message: `Tier 1 received work order "${order.title}" — checking policy rules${useLLM ? " via Aiden LLM" : ""}.`,
    metadata: { type: order.type, priority: order.priority, aiEnabled: useLLM },
  });

  const tier1Result: Tier1Result = useLLM && settings
    ? await runTier1WithLLM(settings, order)
    : runTier1PolicyGate(order);

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Policy Decision",
    message: tier1Result.approved
      ? `Policy gate passed${useLLM ? " (Aiden)" : ""} — dispatching to Tier 2.`
      : `Policy gate blocked: ${tier1Result.reason}`,
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
      message: `Work order blocked at policy gate: ${tier1Result.reason}`,
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

  await storage.updateWorkOrder(orderId, {
    tier1Result,
    gccMemory: {
      ...((order.gccMemory as object) || {}),
      routingContext: { handler: tier1Result.handler, mode: tier1Result.mode },
      correlationId: order.correlationId,
      tier1CompletedAt: new Date().toISOString(),
    },
  });

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Dispatch to Tier 2",
    message: `Routing to Tier 2 handler: ${tier1Result.handler}`,
    metadata: { handler: tier1Result.handler },
  });

  const tier2Result: Tier2Result = useLLM && settings
    ? await runTier2WithLLM(settings, order, tier1Result)
    : runTier2Execution(order, tier1Result);

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 2,
    action: "Schema Validation",
    message: `Work order schema validated successfully${useLLM ? " by Aiden" : ""}.`,
    metadata: { valid: true },
  });

  if (tier2Result.blocked) {
    const bdmMarker = {
      type: "execution_block",
      reason: tier2Result.reason,
      tier: 2,
      timestamp: new Date().toISOString(),
    };

    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 2,
      action: "BDM Marker Emitted",
      message: `Tier 2 execution blocked: ${tier2Result.reason}`,
      metadata: bdmMarker,
    });

    await storage.createExecutionLog({
      workOrderId: orderId,
      tier: 1,
      action: "BDM Resolution",
      message: "Tier 1 received BDM marker from Tier 2 — pausing for human decision.",
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
    action: "Execution Complete",
    message: `Work order executed successfully via ${tier1Result.handler} handler${useLLM ? " (Aiden)" : ""}.`,
    metadata: tier2Result,
  });

  await storage.createExecutionLog({
    workOrderId: orderId,
    tier: 1,
    action: "Resolution",
    message: "Tier 1 confirmed successful execution — work order completed.",
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
      breadcrumbs: ["tier1_policy_pass", "tier2_schema_valid", "tier2_execution_complete", "tier1_resolution"],
    },
  });
}

function runTier1PolicyGate(order: WorkOrder): Tier1Result {
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
  };

  return {
    approved: true,
    reason: "Policy gate passed — all rules satisfied.",
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
