import OpenAI from "openai";
import Anthropic from "@anthropic-ai/sdk";
import type { LlmSettings, WorkOrder, SubAgent } from "@shared/schema";
import { z } from "zod";

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
  }).optional(),
});

export type Tier1Result = z.infer<typeof tier1ResponseSchema>;
export type Tier2Result = z.infer<typeof tier2ResponseSchema>;

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

function getApiKey(envVar: string): string {
  const key = process.env[envVar];
  if (!key) {
    throw new Error(`API key not configured. Please set the ${envVar} secret.`);
  }
  return key;
}

async function callOpenAICompatible(
  settings: LlmSettings,
  messages: Array<{ role: string; content: string }>
): Promise<string> {
  const config = getProviderConfig(settings);
  const apiKey = getApiKey(config.apiKeyEnvVar);

  const client = new OpenAI({
    apiKey,
    baseURL: config.baseURL,
  });

  const params: any = {
    model: settings.model,
    messages: messages as any,
    temperature: 0.3,
  };

  if (settings.provider === "openai") {
    params.response_format = { type: "json_object" };
  }

  const response = await client.chat.completions.create(params);

  return response.choices[0]?.message?.content || "{}";
}

async function callAnthropic(
  settings: LlmSettings,
  systemPrompt: string,
  userMessage: string
): Promise<string> {
  const apiKey = getApiKey("ANTHROPIC_API_KEY");

  const client = new Anthropic({
    apiKey,
  });

  const response = await client.messages.create({
    model: settings.model,
    max_tokens: 1024,
    system: systemPrompt,
    messages: [{ role: "user", content: userMessage }],
  });

  const textBlock = response.content.find((b) => b.type === "text");
  return textBlock?.text || "{}";
}

async function callLLM(settings: LlmSettings, systemPrompt: string, userMessage: string): Promise<string> {
  if (settings.provider === "anthropic") {
    return callAnthropic(settings, systemPrompt, userMessage);
  }

  return callOpenAICompatible(settings, [
    { role: "system", content: systemPrompt },
    { role: "user", content: userMessage },
  ]);
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
    const parsed = JSON.parse(jsonMatch ? jsonMatch[0] : raw);
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
  tier1Result: Tier1Result
): Promise<Tier2Result> {
  const prompt = `You are Aiden, controlling a Tier 2 sub-agent. The work order has passed your Tier 1 policy gate and was routed to handler "${tier1Result.handler}".

Validate the schema and execute the work order. Decide if execution can proceed or if a BDM marker should be emitted.

Respond with ONLY a JSON object in this exact format:
{
  "blocked": true/false,
  "reason": "explanation" or null if not blocked,
  "executionId": "exec_<unique_id>" or null if blocked,
  "handler": "${tier1Result.handler}",
  "output": { "message": "result description" }
}

Work Order:
- Title: ${order.title}
- Description: ${order.description}
- Type: ${order.type}
- Priority: ${order.priority}
- Tier 1 Mode: ${tier1Result.mode}
- Handler: ${tier1Result.handler}`;

  try {
    const raw = await callLLM(settings, settings.systemPrompt, prompt);
    const jsonMatch = raw.match(/\{[\s\S]*\}/);
    const parsed = JSON.parse(jsonMatch ? jsonMatch[0] : raw);
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
