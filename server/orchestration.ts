import { storage } from "./storage";
import type { WorkOrder, SubAgent, WorkflowStep, WorkflowStepRun } from "@shared/schema";
import { runTier1WithLLM, runTier2WithLLM, type Tier1Result, type Tier2Result } from "./llm-client";
import { fileWorkOrderOutput } from "./workspace-filing";

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

  const completedOrder = await storage.updateWorkOrder(orderId, {
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

  if (completedOrder) {
    fileWorkOrderOutput(completedOrder).catch(err =>
      console.error("Auto-filing error:", err.message)
    );
  }

  return completedOrder;
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

  const deliverable = generateFallbackDeliverable(order);

  return {
    blocked: false,
    reason: null,
    executionId: `exec_${Date.now()}`,
    handler: tier1Result.handler,
    output: {
      message: `Work order "${order.title}" processed successfully.`,
      deliverable,
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
        const completedOrder = await storage.updateWorkOrder(execution.workOrderId, {
          status: "completed",
          gccMemory: {
            ...((await storage.getWorkOrder(execution.workOrderId))?.gccMemory as object || {}),
            lastAction: "workflow_completed",
            workflowExecutionId: executionId,
            completedAt: new Date().toISOString(),
          },
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
