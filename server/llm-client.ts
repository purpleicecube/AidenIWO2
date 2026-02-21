import OpenAI from "openai";
import Anthropic from "@anthropic-ai/sdk";
import type { LlmSettings, WorkOrder, SubAgent } from "@shared/schema";
import { z } from "zod";

export interface EffectiveLlmConfig {
  provider: string;
  model: string;
  baseUrl: string | null;
  systemPrompt: string;
  apiKeyEnvVar: string;
  directApiKey?: string;
  source: "sub-agent" | "global";
  subAgentName?: string;
}

function isEnvVarName(value: string): boolean {
  return /^[A-Z][A-Z0-9_]*$/.test(value);
}

function safeJsonParse(jsonStr: string): any {
  try {
    return JSON.parse(jsonStr);
  } catch {
    let cleaned = jsonStr
      .replace(/^```(?:json)?\s*/i, '')
      .replace(/\s*```\s*$/, '')
      .trim();

    const firstBrace = cleaned.indexOf('{');
    const lastBrace = cleaned.lastIndexOf('}');
    if (firstBrace !== -1 && lastBrace > firstBrace) {
      cleaned = cleaned.substring(firstBrace, lastBrace + 1);
    }

    try {
      return JSON.parse(cleaned);
    } catch {
      const sanitized = cleaned.replace(
        /"(?:[^"\\]|\\.)*"/g,
        (match) => {
          const inner = match.slice(1, -1);
          const escaped = inner
            .replace(/(?<!\\)\n/g, '\\n')
            .replace(/(?<!\\)\r/g, '\\r')
            .replace(/(?<!\\)\t/g, '\\t')
            .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '');
          return `"${escaped}"`;
        }
      );
      return JSON.parse(sanitized);
    }
  }
}

export function resolveSubAgentLlmConfig(
  subAgent: SubAgent | null | undefined,
  globalSettings: LlmSettings | undefined
): EffectiveLlmConfig | null {
  if (subAgent?.llmEnabled && subAgent.llmProvider && subAgent.llmModel) {
    const defaultKeyMap: Record<string, string> = {
      openai: "OPENAI_API_KEY",
      anthropic: "ANTHROPIC_API_KEY",
      openrouter: "OPENROUTER_API_KEY",
      groq: "GROQ_API_KEY",
    };

    const rawKeyField = subAgent.llmApiKeyEnvVar?.trim() || "";
    let apiKey: string | undefined;
    let apiKeyEnvVar: string;
    let directApiKey: string | undefined;

    if (rawKeyField && !isEnvVarName(rawKeyField)) {
      directApiKey = rawKeyField;
      apiKey = rawKeyField;
      apiKeyEnvVar = defaultKeyMap[subAgent.llmProvider] || "OPENAI_API_KEY";
    } else {
      apiKeyEnvVar = rawKeyField || defaultKeyMap[subAgent.llmProvider] || "OPENAI_API_KEY";
      apiKey = process.env[apiKeyEnvVar];
    }

    if (!apiKey) {
      console.warn(`Sub-agent "${subAgent.name}" LLM key not found (checked: ${apiKeyEnvVar}), falling back to global.`);
    } else {
      const defaultPrompt = `You are a Tier 2 sub-agent named "${subAgent.name}" (type: ${subAgent.type}). You execute work orders and produce deliverables as directed by Aiden, the Tier 1 orchestration manager.${subAgent.description ? ` Your specialization: ${subAgent.description}` : ""}\n\nProduce high-quality, complete deliverables. Use markdown formatting.`;

      return {
        provider: subAgent.llmProvider,
        model: subAgent.llmModel,
        baseUrl: subAgent.llmBaseUrl || null,
        systemPrompt: subAgent.llmSystemPrompt || defaultPrompt,
        apiKeyEnvVar,
        directApiKey,
        source: "sub-agent",
        subAgentName: subAgent.name,
      };
    }
  }

  if (globalSettings?.enabled) {
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
      systemPrompt: globalSettings.systemPrompt,
      apiKeyEnvVar: globalKeyMap[globalSettings.provider] || "OPENAI_API_KEY",
      source: "global",
    };
  }

  return null;
}

export function effectiveConfigToSettings(config: EffectiveLlmConfig): LlmSettings {
  return {
    id: "effective",
    provider: config.provider,
    model: config.model,
    baseUrl: config.baseUrl,
    systemPrompt: config.systemPrompt,
    enabled: true,
    updatedAt: new Date(),
  };
}

const tier1ResponseSchema = z.object({
  approved: z.boolean(),
  reason: z.string(),
  mode: z.string(),
  handler: z.string().nullable(),
});

const tier2ResponseSchema = z.object({
  blocked: z.boolean(),
  reason: z.string().nullable(),
  executionId: z.string().nullable(),
  handler: z.string().nullable(),
  output: z.object({
    message: z.string(),
    deliverable: z.string().optional(),
    deliverableType: z.enum(["document", "code", "image", "mixed"]).optional(),
    deliverableTitle: z.string().optional(),
  }).optional(),
  pocketflow: z.object({
    iterations: z.number().optional(),
    convergenceScore: z.number().optional(),
    stepResults: z.array(z.object({
      stepId: z.string(),
      stepName: z.string(),
      output: z.string(),
      iteration: z.number(),
    })).optional(),
    refinementHistory: z.array(z.object({
      iteration: z.number(),
      gaps: z.array(z.string()),
      deltaSteps: z.array(z.string()),
    })).optional(),
    bdmMarker: z.any().optional(),
  }).optional(),
});

export type Tier1Result = z.infer<typeof tier1ResponseSchema>;
export type Tier2Result = z.infer<typeof tier2ResponseSchema>;

const planStepsSchema = z.array(z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  dependencies: z.array(z.string()).default([]),
}));

const execStepResultSchema = z.object({
  blocked: z.boolean(),
  reason: z.string().nullable().optional(),
  output: z.string().optional(),
});

const evaluateResultSchema = z.object({
  score: z.number().min(0).max(1),
  meetsCriteria: z.boolean(),
  gaps: z.array(z.string()).default([]),
  strengths: z.array(z.string()).default([]),
  reasoning: z.string(),
});

const refineResultSchema = z.object({
  gaps: z.array(z.string()),
  deltaSteps: z.array(z.object({
    id: z.string(),
    name: z.string(),
    description: z.string(),
    dependencies: z.array(z.string()).default([]),
  })),
  reasoning: z.string(),
});

function getProviderConfig(settings: LlmSettings): { baseURL: string; apiKeyEnvVar: string } {
  switch (settings.provider) {
    case "openrouter":
      return {
        baseURL: settings.baseUrl || "https://openrouter.ai/api/v1",
        apiKeyEnvVar: "OPENROUTER_API_KEY",
      };
    case "groq":
      return {
        baseURL: settings.baseUrl || "https://api.groq.com/openai/v1",
        apiKeyEnvVar: "GROQ_API_KEY",
      };
    case "openai":
      return {
        baseURL: settings.baseUrl || "https://api.openai.com/v1",
        apiKeyEnvVar: "OPENAI_API_KEY",
      };
    case "anthropic":
      return {
        baseURL: "",
        apiKeyEnvVar: "ANTHROPIC_API_KEY",
      };
    default:
      return {
        baseURL: settings.baseUrl || "https://api.openai.com/v1",
        apiKeyEnvVar: "OPENAI_API_KEY",
      };
  }
}

function getApiKey(envVarOrDirectKey: string): string {
  if (!isEnvVarName(envVarOrDirectKey)) {
    return envVarOrDirectKey;
  }
  const key = process.env[envVarOrDirectKey];
  if (!key) {
    throw new Error(`API key not configured. Please set the ${envVarOrDirectKey} secret.`);
  }
  return key;
}

async function callOpenAICompatible(
  settings: LlmSettings,
  messages: Array<{ role: string; content: string }>,
  apiKeyEnvVarOverride?: string
): Promise<string> {
  const config = getProviderConfig(settings);
  const apiKey = getApiKey(apiKeyEnvVarOverride || config.apiKeyEnvVar);

  const client = new OpenAI({
    apiKey,
    baseURL: config.baseURL,
  });

  const params: any = {
    model: settings.model,
    messages: messages as any,
    temperature: 0.3,
    response_format: { type: "json_object" },
  };

  const response = await client.chat.completions.create(params);

  return response.choices[0]?.message?.content || "{}";
}

async function callAnthropic(
  settings: LlmSettings,
  systemPrompt: string,
  userMessage: string,
  apiKeyOverride?: string
): Promise<string> {
  const apiKey = getApiKey(apiKeyOverride || "ANTHROPIC_API_KEY");

  const client = new Anthropic({
    apiKey,
  });

  const response = await client.messages.create({
    model: settings.model,
    max_tokens: 4096,
    system: systemPrompt,
    messages: [{ role: "user", content: userMessage }],
  });

  const textBlock = response.content.find((b) => b.type === "text");
  return textBlock?.text || "{}";
}

async function callLLM(settings: LlmSettings, systemPrompt: string, userMessage: string, apiKeyEnvVarOverride?: string): Promise<string> {
  if (settings.provider === "anthropic") {
    return callAnthropic(settings, systemPrompt, userMessage, apiKeyEnvVarOverride);
  }

  return callOpenAICompatible(settings, [
    { role: "system", content: systemPrompt },
    { role: "user", content: userMessage },
  ], apiKeyEnvVarOverride);
}

export async function chatWithAiden(
  settings: LlmSettings,
  userMessage: string,
  conversationHistory: Array<{ role: string; content: string }>,
  systemContext: string
): Promise<string> {
  const chatSystemPrompt = `${settings.systemPrompt}

${systemContext}

You are Aiden, the intelligent Tier 1 orchestration manager for the AIDEN_PTIB platform. You are having a direct conversation with your operator. Answer questions about work orders, sub-agents, workflows, system status, and operations. Be helpful, concise, and informative. Use the system context provided to give accurate, data-driven answers. If you don't have enough information to answer, say so clearly.

Respond in natural language (not JSON). Use markdown formatting when helpful for readability.

## CREATING WORK ORDERS
When the operator asks you to create, open, or submit a work order:
1. Confirm you are creating it.
2. State the Title, Type, Priority, and Description clearly in your response.
3. Do NOT invent a work-order ID — the system assigns IDs automatically.
4. Tell the operator the work order will appear on the dashboard.

If possible, append a machine-readable action block at the very end of your response on its own line:
<!-- AIDEN_ACTION:CREATE_WORK_ORDER:{"title":"...","description":"...","type":"...","priority":"...","submittedBy":"aiden","autoProcess":true} -->
This helps the system process faster, but is optional — the system will detect your intent either way.`;

  if (settings.provider === "anthropic") {
    const apiKey = getApiKey("ANTHROPIC_API_KEY");
    const client = new Anthropic({ apiKey });
    const messages = [
      ...conversationHistory.map(m => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      })),
      { role: "user" as const, content: userMessage },
    ];
    const response = await client.messages.create({
      model: settings.model,
      max_tokens: 2048,
      system: chatSystemPrompt,
      messages,
    });
    const textBlock = response.content.find((b) => b.type === "text");
    return textBlock?.text || "I could not generate a response.";
  }

  const config = getProviderConfig(settings);
  const apiKey = getApiKey(config.apiKeyEnvVar);
  const client = new OpenAI({ apiKey, baseURL: config.baseURL });
  const messages = [
    { role: "system", content: chatSystemPrompt },
    ...conversationHistory.map(m => ({ role: m.role, content: m.content })),
    { role: "user", content: userMessage },
  ];
  const response = await client.chat.completions.create({
    model: settings.model,
    messages: messages as any,
    temperature: 0.5,
    max_tokens: 2048,
  });
  return response.choices[0]?.message?.content || "I could not generate a response.";
}

export interface ExtractedWorkOrder {
  shouldCreate: boolean;
  title: string;
  description: string;
  type: string;
  priority: string;
}

export async function extractWorkOrderFromChat(
  settings: LlmSettings,
  userMessage: string,
  aidenReply: string,
): Promise<ExtractedWorkOrder | null> {
  const extractionPrompt = `You are a JSON extraction assistant. Your ONLY job is to read a conversation between a user and an AI assistant, and determine if the assistant agreed to create a work order. If yes, extract the details.

RESPOND WITH ONLY A JSON OBJECT, no other text. The JSON must have these fields:
- "shouldCreate": true or false
- "title": string (the work order title)
- "description": string (what needs to be done)
- "type": one of: general, technical, creative, research, compliance, financial, hr, operations, strategic, process_documentation, training, security, infrastructure
- "priority": one of: low, medium, high, critical

If the assistant did NOT agree to create a work order, respond: {"shouldCreate":false,"title":"","description":"","type":"general","priority":"medium"}

Example input:
User: "Create a work order to fix the login bug"
Assistant: "I've created a work order to fix the login bug. Title: Fix login authentication bug, Type: technical, Priority: high"

Example output:
{"shouldCreate":true,"title":"Fix login authentication bug","description":"Fix the login bug that is preventing users from authenticating properly.","type":"technical","priority":"high"}`;

  const extractionInput = `User: "${userMessage}"\nAssistant: "${aidenReply}"`;

  try {
    let raw: string;
    if (settings.provider === "anthropic") {
      raw = await callAnthropic(settings, extractionPrompt, extractionInput);
    } else {
      raw = await callLLM(settings, extractionPrompt, extractionInput);
    }

    raw = raw.trim();
    const jsonMatch = raw.match(/\{[\s\S]*\}/);
    if (!jsonMatch) return null;

    const parsed = JSON.parse(jsonMatch[0]);
    if (!parsed.shouldCreate) return null;
    if (!parsed.title || parsed.title.length < 2) return null;

    return {
      shouldCreate: true,
      title: String(parsed.title).slice(0, 200),
      description: String(parsed.description || "").slice(0, 5000),
      type: String(parsed.type || "general").toLowerCase().replace(/\s+/g, "_"),
      priority: String(parsed.priority || "medium").toLowerCase(),
    };
  } catch (err) {
    console.error("[extractWorkOrderFromChat] Extraction LLM call failed:", err);
    return null;
  }
}

function buildReopenContext(gcc: Record<string, any>): string {
  const metadata = gcc["gcc.metadata"] || {};
  const reopenReason = metadata.reopenReason || gcc.reopenReason;
  const reopenCount = metadata.reopenCount || 1;
  const previousDeliverable = metadata.previousDeliverable;
  const commitIndex = gcc["gcc.commit_index"] || [];
  const lastCommit = commitIndex.length > 0 ? commitIndex[commitIndex.length - 1] : null;

  if (!reopenReason) return "";

  let context = `\n=== REOPEN CONTEXT (Revision #${reopenCount}) ===\n`;
  context += `Reason for reopening: ${reopenReason}\n`;
  if (previousDeliverable && previousDeliverable !== "no_previous_output") {
    context += `\nPrevious deliverable reference:\n${previousDeliverable}\n`;
  }
  if (lastCommit?.detail) {
    context += `\nAudit trail: ${lastCommit.detail}\n`;
  }
  context += `\nINSTRUCTION: This work order was previously completed and has been reopened for revision. The user expects a DIFFERENT and IMPROVED output that directly addresses the reopen reason stated above. Do NOT simply repeat the previous output.\n`;
  context += `=== END REOPEN CONTEXT ===\n`;

  return context;
}

export async function runTier1WithLLM(
  settings: LlmSettings,
  order: WorkOrder,
  subAgents: SubAgent[] = []
): Promise<Tier1Result> {
  const subAgentInfo = subAgents.length > 0
    ? `\n\nAvailable Sub-Agents (Tier 2 Workers):\n${subAgents.map((a) =>
        `- "${a.name}" (type: ${a.type}, mode: ${a.controlMode}${a.assignedTo ? `, operator: ${a.assignedTo}` : ""}${a.description ? `, description: ${a.description}` : ""})`
      ).join("\n")}`
    : "\n\nNo sub-agents configured. Use default handler names.";

  const gcc = (order.gccMemory || {}) as Record<string, any>;
  const isReopened = order.status === "reopened" || gcc["gcc.last_action"] === "reopened";
  const reopenContext = isReopened ? buildReopenContext(gcc) : "";

  const prompt = `You are Aiden, the Tier 1 orchestration manager. Evaluate this work order and decide whether to approve or block it. If approved, choose which sub-agent or handler to route it to.

Respond with ONLY a JSON object in this exact format:
{
  "approved": true/false,
  "reason": "explanation of your decision",
  "mode": "auto" or "manual_review",
  "handler": "handler_name" or null if blocked
}

Available handlers: general_executor, deploy_executor, maintenance_executor, incident_executor, change_executor, security_executor
${subAgentInfo}
${reopenContext}
Work Order:
- Title: ${order.title}
- Description: ${order.description}
- Type: ${order.type}
- Priority: ${order.priority}
- Submitted By: ${order.submittedBy || "system"}
- Correlation ID: ${order.correlationId}`;

  try {
    const raw = await callLLM(settings, settings.systemPrompt, prompt);
    const jsonMatch = raw.match(/\{[\s\S]*\}/);
    const jsonStr = jsonMatch ? jsonMatch[0] : raw;
    const parsed = safeJsonParse(jsonStr);
    return tier1ResponseSchema.parse(parsed);
  } catch (err: any) {
    console.error("Tier 1 LLM error:", err.message);
    return {
      approved: false,
      reason: `LLM evaluation failed: ${err.message}. Blocking for safety.`,
      mode: "manual_review",
      handler: null,
    };
  }
}

export async function runTier2WithLLM(
  settings: LlmSettings,
  order: WorkOrder,
  tier1Result: Tier1Result,
  effectiveConfig?: EffectiveLlmConfig | null
): Promise<Tier2Result> {
  const useConfig = effectiveConfig || null;
  const effectiveSettings = useConfig ? effectiveConfigToSettings(useConfig) : settings;
  const effectiveSystemPrompt = useConfig ? useConfig.systemPrompt : settings.systemPrompt;
  const effectiveApiKey = useConfig?.directApiKey || (useConfig ? useConfig.apiKeyEnvVar : undefined);
  const agentLabel = useConfig?.source === "sub-agent"
    ? `You are "${useConfig.subAgentName}", a specialized Tier 2 sub-agent. You are independently executing this work order using your own capabilities and LLM configuration.`
    : `You are Aiden, controlling a Tier 2 sub-agent.`;

  const gcc = (order.gccMemory || {}) as Record<string, any>;
  const isReopened = gcc["gcc.last_action"] === "reopened" || gcc.lastAction === "reopened";
  const reopenContext = isReopened ? buildReopenContext(gcc) : "";

  const prompt = `${agentLabel} The work order has passed the Tier 1 policy gate and was routed to handler "${tier1Result.handler}".

Validate the schema and execute the work order. Decide if execution can proceed or if a BDM marker should be emitted.

IMPORTANT: If not blocked, you MUST produce the actual deliverable — the real work product the user requested. For example:
- If the work order asks to "draft an email", write the full email in the deliverable field.
- If it asks to "create a deployment plan", write the full plan.
- If it asks to "update documentation", write the actual documentation content.
- If it asks to "investigate an incident", write the investigation report.
The deliverable should be the complete, ready-to-use output — not just a summary or status message.
${reopenContext ? `\n${reopenContext}\nCRITICAL: This is a REOPENED work order. You MUST produce a REVISED deliverable that directly addresses the reopen reason above. Do NOT reproduce the previous output — incorporate the new requirements, feedback, or information that prompted the reopen.\n` : ""}
Respond with ONLY a JSON object in this exact format:
{
  "blocked": true/false,
  "reason": "explanation" or null if not blocked,
  "executionId": "exec_<unique_id>" or null if blocked,
  "handler": "${tier1Result.handler}",
  "output": {
    "message": "brief one-line summary of what was produced",
    "deliverable": "THE FULL WORK PRODUCT CONTENT HERE — the actual email, plan, report, documentation, etc. Use markdown formatting.",
    "deliverableType": "document" or "code" or "image" or "mixed",
    "deliverableTitle": "short filename-friendly title for the deliverable, e.g. Q1-Security-Review-Email"
  }
}

deliverableType guide:
- "document" — emails, reports, plans, memos, proposals, SOPs, reviews
- "code" — scripts, configurations, code snippets, YAML/JSON, infrastructure-as-code
- "image" — when the output describes an image (rare for text LLMs)
- "mixed" — when the output contains both code and documents

Work Order:
- Title: ${order.title}
- Description: ${order.description}
- Type: ${order.type}
- Priority: ${order.priority}
- Tier 1 Mode: ${tier1Result.mode}
- Handler: ${tier1Result.handler}`;

  try {
    const raw = await callLLM(effectiveSettings, effectiveSystemPrompt, prompt, effectiveApiKey);
    const jsonMatch = raw.match(/\{[\s\S]*\}/);
    const jsonStr = jsonMatch ? jsonMatch[0] : raw;
    const parsed = safeJsonParse(jsonStr);
    return tier2ResponseSchema.parse(parsed);
  } catch (err: any) {
    console.error("Tier 2 LLM error:", err.message);
    return {
      blocked: true,
      reason: `LLM execution failed: ${err.message}. Emitting BDM marker.`,
      executionId: null,
      handler: tier1Result.handler,
    };
  }
}

export async function testLLMConnection(settings: LlmSettings): Promise<{ success: boolean; message: string }> {
  const config = getProviderConfig(settings);
  const apiKey = getApiKey(config.apiKeyEnvVar);

  const testPrompt = "Respond with exactly this JSON: {\"status\": \"ok\"}";

  if (settings.provider === "anthropic") {
    const client = new Anthropic({ apiKey });
    const response = await client.messages.create({
      model: settings.model,
      max_tokens: 64,
      messages: [{ role: "user", content: testPrompt }],
    });
    const textBlock = response.content.find((b) => b.type === "text");
    if (!textBlock?.text) {
      throw new Error("Empty response from Anthropic");
    }
    return { success: true, message: `Connected to ${settings.provider} (${settings.model})` };
  }

  const client = new OpenAI({ apiKey, baseURL: config.baseURL });

  const response = await client.chat.completions.create({
    model: settings.model,
    messages: [{ role: "user", content: testPrompt }],
    max_tokens: 64,
  });

  if (!response.choices?.[0]?.message?.content) {
    throw new Error("Empty response from provider");
  }

  return { success: true, message: `Connected to ${settings.provider} (${settings.model})` };
}

export function getRequiredApiKeyName(provider: string): string {
  switch (provider) {
    case "openrouter": return "OPENROUTER_API_KEY";
    case "groq": return "GROQ_API_KEY";
    case "openai": return "OPENAI_API_KEY";
    case "anthropic": return "ANTHROPIC_API_KEY";
    default: return "OPENAI_API_KEY";
  }
}

export function isApiKeyConfigured(provider: string): boolean {
  const envVar = getRequiredApiKeyName(provider);
  return !!process.env[envVar];
}

export interface ProviderModel {
  id: string;
  name: string;
  contextWindow?: number;
  owned_by?: string;
}

export async function llmPlanSteps(
  settings: LlmSettings,
  systemPrompt: string,
  order: WorkOrder,
  tier1Result: Tier1Result,
  existingGaps: string[],
  existingOutputs: Record<string, string>,
  apiKeyOverride?: string
): Promise<Array<{ id: string; name: string; description: string; dependencies: string[] }>> {
  const isRefinement = existingGaps.length > 0;
  const existingContext = Object.entries(existingOutputs).length > 0
    ? `\nAlready completed outputs:\n${Object.entries(existingOutputs).map(([id, out]) => `- ${id}: ${out.substring(0, 200)}...`).join("\n")}`
    : "";
  const gapsContext = isRefinement
    ? `\nThis is a REFINEMENT pass. Only plan steps to address these gaps:\n${existingGaps.map(g => `- ${g}`).join("\n")}${existingContext}`
    : "";

  const prompt = `You are executing a work order as a Tier 2 sub-agent. Break the work order into concrete execution steps.
${gapsContext}
Each step should be a discrete unit of work. Steps can declare dependencies on other steps by ID.
Independent steps (no dependencies) will be executed in PARALLEL for efficiency.

Respond with ONLY a JSON array:
[
  { "id": "step_1", "name": "Step Name", "description": "What to do", "dependencies": [] },
  { "id": "step_2", "name": "Step Name", "description": "What to do", "dependencies": ["step_1"] }
]

${isRefinement ? "IMPORTANT: Only add NEW steps needed to fill gaps. Use new unique IDs (e.g. step_r1, step_r2). Reference existing step IDs in dependencies if needed." : ""}
For simple work orders, a single step is perfectly fine.

Work Order:
- Title: ${order.title}
- Description: ${order.description}
- Type: ${order.type}
- Priority: ${order.priority}
- Handler: ${tier1Result.handler}`;

  const raw = await callLLM(settings, systemPrompt, prompt, apiKeyOverride);
  const jsonMatch = raw.match(/\[[\s\S]*\]/);
  const jsonStr = jsonMatch ? jsonMatch[0] : raw;
  const parsed = safeJsonParse(jsonStr);
  return planStepsSchema.parse(parsed);
}

export async function llmExecStep(
  settings: LlmSettings,
  systemPrompt: string,
  order: WorkOrder,
  step: { id: string; name: string; description: string },
  previousOutputs: Record<string, string>,
  apiKeyOverride?: string
): Promise<{ blocked: boolean; reason?: string | null; output?: string }> {
  const contextEntries = Object.entries(previousOutputs);
  const prevContext = contextEntries.length > 0
    ? `\nPrevious step outputs available:\n${contextEntries.map(([id, out]) => `--- ${id} ---\n${out}`).join("\n\n")}`
    : "";

  const gcc = (order.gccMemory || {}) as Record<string, any>;
  const isReopened = gcc["gcc.last_action"] === "reopened" || gcc.lastAction === "reopened";
  const reopenContext = isReopened ? buildReopenContext(gcc) : "";

  const prompt = `You are executing step "${step.name}" of a work order.

Step description: ${step.description}
${prevContext}
${reopenContext}
Work Order Context:
- Title: ${order.title}
- Description: ${order.description}
- Type: ${order.type}
- Priority: ${order.priority}

IMPORTANT: Produce the ACTUAL deliverable content for this step. Write the real work product — not a summary or status.
If this step cannot be executed (missing info, external dependency, etc.), set blocked=true.

Respond with ONLY a JSON object:
{
  "blocked": false,
  "reason": null,
  "output": "THE ACTUAL CONTENT/DELIVERABLE FOR THIS STEP in markdown"
}`;

  const raw = await callLLM(settings, systemPrompt, prompt, apiKeyOverride);
  const jsonMatch = raw.match(/\{[\s\S]*\}/);
  const jsonStr = jsonMatch ? jsonMatch[0] : raw;
  const parsed = safeJsonParse(jsonStr);
  return execStepResultSchema.parse(parsed);
}

export async function llmEvaluate(
  settings: LlmSettings,
  systemPrompt: string,
  order: WorkOrder,
  combinedOutput: string,
  planSteps: Array<{ id: string; name: string; status: string }>,
  apiKeyOverride?: string
): Promise<{ score: number; meetsCriteria: boolean; gaps: string[]; strengths: string[]; reasoning: string }> {
  const prompt = `You are evaluating the quality and completeness of a work order's deliverable.

Work Order:
- Title: ${order.title}
- Description: ${order.description}
- Type: ${order.type}
- Priority: ${order.priority}

Steps executed: ${planSteps.filter(s => s.status === "completed").map(s => s.name).join(", ")}
Steps failed: ${planSteps.filter(s => s.status === "failed").map(s => s.name).join(", ") || "none"}

Combined output to evaluate:
${combinedOutput.substring(0, 4000)}

Score the output from 0.0 to 1.0:
- 0.0-0.3: Missing most requirements, incomplete
- 0.4-0.6: Partially complete, major gaps
- 0.7-0.8: Mostly complete, minor improvements possible
- 0.8-1.0: Comprehensive, meets all criteria

Respond with ONLY a JSON object:
{
  "score": 0.85,
  "meetsCriteria": true,
  "gaps": ["gap description if any"],
  "strengths": ["what was done well"],
  "reasoning": "brief explanation of score"
}`;

  const raw = await callLLM(settings, systemPrompt, prompt, apiKeyOverride);
  const jsonMatch = raw.match(/\{[\s\S]*\}/);
  const jsonStr = jsonMatch ? jsonMatch[0] : raw;
  const parsed = safeJsonParse(jsonStr);
  return evaluateResultSchema.parse(parsed);
}

export async function llmRefine(
  settings: LlmSettings,
  systemPrompt: string,
  order: WorkOrder,
  gaps: string[],
  existingOutputs: Record<string, string>,
  planSteps: Array<{ id: string; name: string; status: string }>,
  apiKeyOverride?: string
): Promise<{ gaps: string[]; deltaSteps: Array<{ id: string; name: string; description: string; dependencies: string[] }>; reasoning: string }> {
  const prompt = `You are refining a work order execution. The previous iteration identified gaps that need to be addressed.

Work Order:
- Title: ${order.title}
- Description: ${order.description}
- Type: ${order.type}

Identified gaps:
${gaps.map(g => `- ${g}`).join("\n")}

Existing completed steps: ${planSteps.filter(s => s.status === "completed").map(s => `${s.id}: ${s.name}`).join(", ")}
Failed steps: ${planSteps.filter(s => s.status === "failed").map(s => `${s.id}: ${s.name}`).join(", ") || "none"}

Existing outputs available:
${Object.entries(existingOutputs).map(([id, out]) => `--- ${id} ---\n${out.substring(0, 300)}...`).join("\n\n")}

Produce ONLY new delta steps needed to fill the gaps. Do NOT re-do completed work.
Use unique IDs like step_r1, step_r2, etc.

Respond with ONLY a JSON object:
{
  "gaps": ["restated gaps being addressed"],
  "deltaSteps": [
    { "id": "step_r1", "name": "Fill Gap Name", "description": "What to produce", "dependencies": [] }
  ],
  "reasoning": "why these steps will address the gaps"
}`;

  const raw = await callLLM(settings, systemPrompt, prompt, apiKeyOverride);
  const jsonMatch = raw.match(/\{[\s\S]*\}/);
  const jsonStr = jsonMatch ? jsonMatch[0] : raw;
  const parsed = safeJsonParse(jsonStr);
  return refineResultSchema.parse(parsed);
}

export async function fetchAvailableModels(provider: string): Promise<ProviderModel[]> {
  const keyName = getRequiredApiKeyName(provider);
  const apiKey = process.env[keyName];
  if (!apiKey) {
    return [];
  }

  try {
    if (provider === "anthropic") {
      return [
        { id: "claude-sonnet-4-5", name: "Claude Sonnet 4.5", contextWindow: 200000 },
        { id: "claude-sonnet-4-20250514", name: "Claude Sonnet 4", contextWindow: 200000 },
        { id: "claude-opus-4-20250514", name: "Claude Opus 4", contextWindow: 200000 },
        { id: "claude-3-5-sonnet-20241022", name: "Claude 3.5 Sonnet", contextWindow: 200000 },
        { id: "claude-3-5-haiku-20241022", name: "Claude 3.5 Haiku", contextWindow: 200000 },
        { id: "claude-3-opus-20240229", name: "Claude 3 Opus", contextWindow: 200000 },
      ];
    }

    if (provider === "openrouter") {
      const res = await fetch("https://openrouter.ai/api/v1/models", {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      if (!res.ok) return [];
      const data = await res.json();
      return (data.data || [])
        .filter((m: any) => m.id)
        .map((m: any) => ({
          id: m.id,
          name: m.name || m.id,
          contextWindow: m.context_length,
          owned_by: m.id.split("/")[0],
        }))
        .slice(0, 200);
    }

    const baseURLMap: Record<string, string> = {
      openai: "https://api.openai.com/v1",
      groq: "https://api.groq.com/openai/v1",
    };

    const baseURL = baseURLMap[provider] || "https://api.openai.com/v1";
    const client = new OpenAI({ apiKey, baseURL });
    const list = await client.models.list();
    const models: ProviderModel[] = [];

    const nonChatPatterns = [
      "whisper",
      "llama-guard",
      "llama-prompt-guard",
      "safeguard",
      "orpheus",
    ];

    for await (const m of list) {
      if (provider === "groq") {
        const lower = m.id.toLowerCase();
        if (nonChatPatterns.some(p => lower.includes(p))) continue;
      }
      models.push({
        id: m.id,
        name: m.id,
        owned_by: m.owned_by,
      });
    }
    models.sort((a, b) => a.id.localeCompare(b.id));
    return models;
  } catch (err: any) {
    console.error(`Failed to fetch models for ${provider}:`, err.message);
    return [];
  }
}
