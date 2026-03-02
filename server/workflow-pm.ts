import type { SubAgent, LlmSettings, WorkflowTemplate, WorkflowStep, WorkflowStepRun } from "@shared/schema";
import { resolveSubAgentLlmConfig, effectiveConfigToSettings, type EffectiveLlmConfig } from "./llm-client";
import { callLLM, callAnthropic } from "./llm-client";

export interface PmReviewResult {
  approved: boolean;
  score: number;
  issues: string[];
  recommendation: "advance" | "revise" | "escalate";
  feedback: string;
}

export interface PmRevisionGuidance {
  revisionInstructions: string;
  focusAreas: string[];
  previousIssues: string[];
}

export interface WorkProductResult {
  summary: string;
  deliverable: string;
  deliverableType: string;
  deliverableTitle: string;
  stepContributions: Record<string, string>;
}

export interface ExecutiveReviewResult {
  approved: boolean;
  score: number;
  feedback: string;
  recommendation: "approve" | "revise" | "escalate_to_operator";
  issues: string[];
}

export interface EscalationResult {
  action: "retry" | "skip" | "abort" | "hitl";
  reason: string;
  guidance?: string;
}

export function resolvePmLlmConfig(
  pmSubAgent: SubAgent | null | undefined,
  template: WorkflowTemplate,
  globalSettings: LlmSettings | undefined
): EffectiveLlmConfig | null {
  const llmMode = template.llmMode || "inherited";

  if (llmMode === "shared_with_aiden") {
    if (!globalSettings?.enabled) return null;
    const globalKeyMap: Record<string, string> = {
      openai: "OPENAI_API_KEY",
      anthropic: "ANTHROPIC_API_KEY",
      openrouter: "OPENROUTER_API_KEY",
      groq: "GROQ_API_KEY",
    };
    return {
      provider: globalSettings.provider,
      model: globalSettings.model,
      baseUrl: globalSettings.baseUrl,
      systemPrompt: buildPmSystemPrompt(pmSubAgent, globalSettings.systemPrompt),
      apiKeyEnvVar: globalKeyMap[globalSettings.provider] || "OPENAI_API_KEY",
      source: "global",
      subAgentName: pmSubAgent?.name,
    };
  }

  if (llmMode === "own_llm") {
    const config = resolveSubAgentLlmConfig(pmSubAgent, undefined);
    if (config) {
      config.systemPrompt = buildPmSystemPrompt(pmSubAgent, config.systemPrompt);
      return config;
    }
    return resolveSubAgentLlmConfig(pmSubAgent, globalSettings);
  }

  const config = resolveSubAgentLlmConfig(pmSubAgent, globalSettings);
  if (config) {
    config.systemPrompt = buildPmSystemPrompt(pmSubAgent, config.systemPrompt);
  }
  return config;
}

function buildPmSystemPrompt(pmSubAgent: SubAgent | null | undefined, basePrompt: string): string {
  const pmName = pmSubAgent?.name || "Workflow PM";
  return `You are ${pmName}, a Project Manager sub-agent in the AIDEN_IWO platform — designed, built, and led by Darrel Vaughn (LuaAzullaB), Lead Developer and Principal Technical Architect.

Your role is to coordinate multi-step workflow executions:
- Review step outputs for quality and completeness
- Provide revision guidance when step outputs don't meet requirements
- Assemble individual step outputs into a cohesive final work product
- Escalate to Aiden (the Executive/Program Manager) when issues require higher authority

You make front-line decisions. You are thorough, objective, and focused on delivering a high-quality final work product that meets the workflow's stated goal.

${pmSubAgent?.description ? `Your specialization: ${pmSubAgent.description}` : ""}`;
}

export async function selectProjectManager(
  template: WorkflowTemplate,
  activeSubAgents: SubAgent[],
  globalSettings: LlmSettings | undefined
): Promise<{ pm: SubAgent | null; llmConfig: EffectiveLlmConfig | null }> {
  if (template.preferredPmId) {
    const preferred = activeSubAgents.find(a => a.id === template.preferredPmId);
    if (preferred) {
      const config = resolvePmLlmConfig(preferred, template, globalSettings);
      return { pm: preferred, llmConfig: config };
    }
  }

  const pmAgents = activeSubAgents.filter(a => a.type === "project_manager" && a.status === "active");

  if (pmAgents.length === 0) {
    return { pm: null, llmConfig: null };
  }

  if (pmAgents.length === 1) {
    const config = resolvePmLlmConfig(pmAgents[0], template, globalSettings);
    return { pm: pmAgents[0], llmConfig: config };
  }

  if (!globalSettings?.enabled) {
    const config = resolvePmLlmConfig(pmAgents[0], template, globalSettings);
    return { pm: pmAgents[0], llmConfig: config };
  }

  try {
    const pmList = pmAgents.map(a =>
      `- "${a.name}" (type: ${a.type}${a.description ? `, description: ${a.description}` : ""})`
    ).join("\n");

    const prompt = `You are Aiden, the Executive/Program Manager. Select the best Project Manager sub-agent for this workflow.

Workflow: "${template.name}"
Goal: ${template.goal || "Not specified"}
Category: ${template.category}

Available Project Managers:
${pmList}

Respond with ONLY a JSON object: {"selectedPm": "exact_pm_name", "reason": "why this PM is the best fit"}`;

    const raw = await callLLMWithConfig(globalSettings, prompt);
    const match = raw.match(/\{[\s\S]*\}/);
    if (match) {
      const parsed = JSON.parse(match[0]);
      const selected = pmAgents.find(a => a.name.toLowerCase() === String(parsed.selectedPm || "").toLowerCase());
      if (selected) {
        const config = resolvePmLlmConfig(selected, template, globalSettings);
        return { pm: selected, llmConfig: config };
      }
    }
  } catch (err) {
    console.error("[workflow-pm] PM selection LLM call failed, using first PM:", err);
  }

  const config = resolvePmLlmConfig(pmAgents[0], template, globalSettings);
  return { pm: pmAgents[0], llmConfig: config };
}

export async function pmReviewStepOutput(
  pmLlmConfig: EffectiveLlmConfig,
  stepDef: WorkflowStep,
  stepOutput: any,
  workflowGoal: string,
  previousResults: Record<string, any>
): Promise<PmReviewResult> {
  const outputStr = typeof stepOutput === "string" ? stepOutput : JSON.stringify(stepOutput, null, 2);
  const prevContext = Object.keys(previousResults).length > 0
    ? `\nPrevious step outputs available: ${Object.keys(previousResults).join(", ")}`
    : "";

  const prompt = `Review the output of workflow step "${stepDef.name}" (key: ${stepDef.stepKey}).

WORKFLOW GOAL: ${workflowGoal}
STEP DESCRIPTION: ${stepDef.description || stepDef.name}
STEP PROMPT: ${stepDef.promptTemplate || "N/A"}
${prevContext}

STEP OUTPUT:
${outputStr.slice(0, 4000)}

Evaluate this step's output against:
1. Does it fulfill the step's specific requirements?
2. Does it contribute meaningfully toward the overall workflow goal?
3. Is the quality sufficient to pass to the next step?

Respond with ONLY a JSON object:
{
  "approved": true/false,
  "score": 0.0-1.0,
  "issues": ["list of specific issues if any"],
  "recommendation": "advance" | "revise" | "escalate",
  "feedback": "brief summary of your assessment"
}

Use "advance" if output is acceptable (score >= 0.7).
Use "revise" if output needs improvement but is salvageable (score 0.4-0.69).
Use "escalate" if output is fundamentally flawed or step cannot proceed (score < 0.4).`;

  try {
    const raw = await callLLMWithConfig(pmLlmConfig, prompt);
    const match = raw.match(/\{[\s\S]*\}/);
    if (match) {
      const parsed = JSON.parse(match[0]);
      return {
        approved: parsed.approved === true,
        score: Math.min(1, Math.max(0, Number(parsed.score) || 0.5)),
        issues: Array.isArray(parsed.issues) ? parsed.issues.map(String) : [],
        recommendation: ["advance", "revise", "escalate"].includes(parsed.recommendation) ? parsed.recommendation : "advance",
        feedback: String(parsed.feedback || ""),
      };
    }
  } catch (err) {
    console.error("[workflow-pm] Step review LLM call failed:", err);
  }

  return {
    approved: true,
    score: 0.7,
    issues: [],
    recommendation: "advance",
    feedback: "PM review LLM unavailable — auto-advancing step.",
  };
}

export async function pmRequestStepRevision(
  pmLlmConfig: EffectiveLlmConfig,
  stepDef: WorkflowStep,
  stepOutput: any,
  reviewResult: PmReviewResult,
  revisionAttempt: number
): Promise<PmRevisionGuidance> {
  const outputStr = typeof stepOutput === "string" ? stepOutput : JSON.stringify(stepOutput, null, 2);

  const prompt = `You are the Project Manager. Step "${stepDef.name}" needs revision (attempt ${revisionAttempt + 1}).

STEP DESCRIPTION: ${stepDef.description || stepDef.name}
PM REVIEW SCORE: ${reviewResult.score}
PM ISSUES FOUND:
${reviewResult.issues.map(i => `- ${i}`).join("\n")}
PM FEEDBACK: ${reviewResult.feedback}

CURRENT OUTPUT (truncated):
${outputStr.slice(0, 3000)}

Generate specific revision instructions for the step agent. Be concrete about what needs to change.

Respond with ONLY a JSON object:
{
  "revisionInstructions": "detailed instructions for the step agent",
  "focusAreas": ["area1", "area2"],
  "previousIssues": ["issue1", "issue2"]
}`;

  try {
    const raw = await callLLMWithConfig(pmLlmConfig, prompt);
    const match = raw.match(/\{[\s\S]*\}/);
    if (match) {
      const parsed = JSON.parse(match[0]);
      return {
        revisionInstructions: String(parsed.revisionInstructions || "Please revise the output to address the identified issues."),
        focusAreas: Array.isArray(parsed.focusAreas) ? parsed.focusAreas.map(String) : reviewResult.issues,
        previousIssues: Array.isArray(parsed.previousIssues) ? parsed.previousIssues.map(String) : reviewResult.issues,
      };
    }
  } catch (err) {
    console.error("[workflow-pm] Revision guidance LLM call failed:", err);
  }

  return {
    revisionInstructions: `Please revise the output. Issues: ${reviewResult.issues.join("; ")}`,
    focusAreas: reviewResult.issues,
    previousIssues: reviewResult.issues,
  };
}

export async function pmAssembleWorkProduct(
  pmLlmConfig: EffectiveLlmConfig,
  workflowGoal: string,
  allStepResults: { stepKey: string; stepName: string; output: any }[],
  templateName: string
): Promise<WorkProductResult> {
  const stepSummaries = allStepResults.map(s => {
    const outputStr = typeof s.output === "string" ? s.output : JSON.stringify(s.output, null, 2);
    return `### Step: ${s.stepName} (${s.stepKey})\n${outputStr.slice(0, 2000)}`;
  }).join("\n\n");

  const prompt = `You are the Project Manager assembling the final work product for workflow "${templateName}".

WORKFLOW GOAL: ${workflowGoal}

COMPLETED STEP OUTPUTS:
${stepSummaries.slice(0, 8000)}

Your job is to synthesize all step outputs into a cohesive, polished final deliverable that meets the workflow's goal. Do not simply concatenate — integrate and organize the outputs into a unified result.

Respond with ONLY a JSON object:
{
  "summary": "executive summary of what was accomplished",
  "deliverable": "the complete assembled work product (full content)",
  "deliverableType": "document" | "code" | "report" | "mixed",
  "deliverableTitle": "title for the work product"
}`;

  try {
    const raw = await callLLMWithConfig(pmLlmConfig, prompt);
    const match = raw.match(/\{[\s\S]*\}/);
    if (match) {
      const parsed = JSON.parse(match[0]);
      const contributions: Record<string, string> = {};
      for (const s of allStepResults) {
        const outStr = typeof s.output === "string" ? s.output : JSON.stringify(s.output);
        contributions[s.stepKey] = outStr.slice(0, 500);
      }
      return {
        summary: String(parsed.summary || "Work product assembled."),
        deliverable: String(parsed.deliverable || ""),
        deliverableType: String(parsed.deliverableType || "document"),
        deliverableTitle: String(parsed.deliverableTitle || templateName),
        stepContributions: contributions,
      };
    }
  } catch (err) {
    console.error("[workflow-pm] Work product assembly LLM call failed:", err);
  }

  const contributions: Record<string, string> = {};
  const parts: string[] = [];
  for (const s of allStepResults) {
    const outStr = typeof s.output === "string" ? s.output : JSON.stringify(s.output);
    contributions[s.stepKey] = outStr.slice(0, 500);
    parts.push(`## ${s.stepName}\n${outStr}`);
  }
  return {
    summary: `Workflow "${templateName}" completed with ${allStepResults.length} steps.`,
    deliverable: parts.join("\n\n"),
    deliverableType: "document",
    deliverableTitle: templateName,
    stepContributions: contributions,
  };
}

export async function pmEscalateToAiden(
  globalSettings: LlmSettings | undefined,
  executionMode: string,
  reason: string,
  context: {
    workflowName: string;
    workflowGoal: string;
    failedStep?: string;
    stepOutput?: any;
    pmReview?: PmReviewResult;
    revisionAttempts?: number;
  }
): Promise<EscalationResult> {
  if (executionMode === "manual") {
    return {
      action: "hitl",
      reason: `Manual mode — PM escalation requires operator intervention. ${reason}`,
    };
  }

  if (!globalSettings?.enabled) {
    return {
      action: executionMode === "semi_autonomous" ? "hitl" : "skip",
      reason: `No LLM available for Aiden review. ${reason}`,
    };
  }

  const prompt = `You are Aiden, the Executive/Program Manager. The Project Manager has escalated an issue during workflow execution.

WORKFLOW: "${context.workflowName}"
GOAL: ${context.workflowGoal}
ESCALATION REASON: ${reason}
${context.failedStep ? `FAILED STEP: ${context.failedStep}` : ""}
${context.revisionAttempts ? `REVISION ATTEMPTS: ${context.revisionAttempts}` : ""}
${context.pmReview ? `PM REVIEW: Score ${context.pmReview.score}, Issues: ${context.pmReview.issues.join("; ")}` : ""}

Decide what action to take:
- "retry": Re-execute the failed step (possibly with a different approach)
- "skip": Skip this step and continue the workflow
- "abort": Abort the entire workflow
${executionMode === "semi_autonomous" ? '- "hitl": Escalate to human operator for manual decision' : ""}

Respond with ONLY a JSON object:
{
  "action": "retry" | "skip" | "abort"${executionMode === "semi_autonomous" ? ' | "hitl"' : ""},
  "reason": "explanation of your decision",
  "guidance": "optional instructions if retrying"
}`;

  try {
    const raw = await callLLMWithConfig(globalSettings, prompt);
    const match = raw.match(/\{[\s\S]*\}/);
    if (match) {
      const parsed = JSON.parse(match[0]);
      const validActions = executionMode === "semi_autonomous"
        ? ["retry", "skip", "abort", "hitl"]
        : ["retry", "skip", "abort"];
      return {
        action: validActions.includes(parsed.action) ? parsed.action : "skip",
        reason: String(parsed.reason || reason),
        guidance: parsed.guidance ? String(parsed.guidance) : undefined,
      };
    }
  } catch (err) {
    console.error("[workflow-pm] Aiden escalation LLM call failed:", err);
  }

  return {
    action: executionMode === "semi_autonomous" ? "hitl" : "skip",
    reason: `Aiden escalation LLM unavailable. ${reason}`,
  };
}

export async function aidenExecutiveReview(
  globalSettings: LlmSettings | undefined,
  workflowGoal: string,
  workProduct: WorkProductResult,
  executionSummary: {
    templateName: string;
    totalSteps: number;
    completedSteps: number;
    skippedSteps: number;
    failedSteps: number;
    pmName: string;
  }
): Promise<ExecutiveReviewResult> {
  if (!globalSettings?.enabled) {
    return {
      approved: true,
      score: 0.7,
      feedback: "Executive review skipped — no LLM available. Auto-approving based on PM's assessment.",
      recommendation: "approve",
      issues: [],
    };
  }

  const prompt = `You are Aiden, the Executive/Program Manager of the AIDEN_IWO platform — designed, built, and led by Darrel Vaughn (LuaAzullaB). Perform a final executive review of this workflow's assembled work product.

WORKFLOW: "${executionSummary.templateName}"
GOAL: ${workflowGoal}
PM: ${executionSummary.pmName}
COMPLETION: ${executionSummary.completedSteps}/${executionSummary.totalSteps} steps completed, ${executionSummary.skippedSteps} skipped, ${executionSummary.failedSteps} failed

WORK PRODUCT SUMMARY: ${workProduct.summary}

WORK PRODUCT DELIVERABLE (truncated):
${workProduct.deliverable.slice(0, 6000)}

Evaluate:
1. Does the combined output satisfy the workflow's stated goal?
2. Are there gaps, contradictions, or quality issues in the assembled work product?
3. Is this ready for delivery to the operator?

Respond with ONLY a JSON object:
{
  "approved": true/false,
  "score": 0.0-1.0,
  "feedback": "executive assessment",
  "recommendation": "approve" | "revise" | "escalate_to_operator",
  "issues": ["list of issues if any"]
}`;

  try {
    const raw = await callLLMWithConfig(globalSettings, prompt);
    const match = raw.match(/\{[\s\S]*\}/);
    if (match) {
      const parsed = JSON.parse(match[0]);
      return {
        approved: parsed.approved === true,
        score: Math.min(1, Math.max(0, Number(parsed.score) || 0.5)),
        feedback: String(parsed.feedback || ""),
        recommendation: ["approve", "revise", "escalate_to_operator"].includes(parsed.recommendation)
          ? parsed.recommendation
          : "approve",
        issues: Array.isArray(parsed.issues) ? parsed.issues.map(String) : [],
      };
    }
  } catch (err) {
    console.error("[workflow-pm] Executive review LLM call failed:", err);
  }

  return {
    approved: true,
    score: 0.7,
    feedback: "Executive review LLM unavailable — auto-approving.",
    recommendation: "approve",
    issues: [],
  };
}

async function callLLMWithConfig(config: LlmSettings | EffectiveLlmConfig, prompt: string): Promise<string> {
  const settings: LlmSettings = "source" in config
    ? effectiveConfigToSettings(config as EffectiveLlmConfig)
    : config as LlmSettings;
  const systemPrompt = settings.systemPrompt || "You are a helpful assistant.";

  const apiKeyOverride = "directApiKey" in config ? (config as EffectiveLlmConfig).directApiKey : undefined;

  if (settings.provider === "anthropic") {
    return callAnthropic(settings, systemPrompt, prompt, apiKeyOverride);
  }
  return callLLM(settings, systemPrompt, prompt, apiKeyOverride);
}
