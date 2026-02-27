import { storage } from "./storage";
import type { Tool, ToolLease } from "@shared/schema";

export interface ToolExecResult {
  success: boolean;
  output: string;
  error?: string;
  toolName: string;
  toolSlug: string;
  leaseId?: string;
  durationMs: number;
}

interface ToolCredential {
  key: string;
  value: string;
  isSecret?: boolean;
  description?: string;
}

function getCredentials(tool: Tool): Record<string, string> {
  const creds = (tool.credentials || []) as ToolCredential[];
  const map: Record<string, string> = {};
  for (const c of creds) {
    if (c.key && c.value) map[c.key] = c.value;
  }
  return map;
}

async function checkoutLease(
  tool: Tool,
  agentId: string,
  workOrderId?: string
): Promise<ToolLease> {
  const now = new Date();
  const expiresAt = new Date(now.getTime() + (tool.defaultLeaseSeconds || 300) * 1000);
  const lease = await storage.createToolLease({
    toolId: tool.id,
    agentId,
    agentType: "sub_agent",
    tier: "tier2",
    leaseType: "checkout",
    status: "active",
    toolVersion: tool.version || "1.0.0",
    context: { automated: true, source: "pocketflow" },
    workOrderId: workOrderId || null,
    expiresAt,
  });
  await storage.createToolAuditLog({
    toolId: tool.id,
    action: "checkout",
    actorId: agentId,
    actorType: "sub_agent",
    reason: `Auto-checkout for work order execution`,
    metadata: { leaseId: lease.id, workOrderId },
  });
  return lease;
}

async function returnLease(
  lease: ToolLease,
  result: ToolExecResult
): Promise<void> {
  await storage.updateToolLease(lease.id, {
    status: "returned",
    returnedAt: new Date(),
    result: { success: result.success, output: result.output.slice(0, 2000) },
    error: result.error || null,
  });
  await storage.createToolAuditLog({
    toolId: lease.toolId,
    action: "return",
    actorId: lease.agentId,
    actorType: "sub_agent",
    reason: result.success ? "Execution completed" : `Execution failed: ${result.error}`,
    metadata: { leaseId: lease.id, durationMs: result.durationMs },
  });
}

async function executeBraveSearch(tool: Tool, input: string): Promise<string> {
  const creds = getCredentials(tool);
  const apiKey = creds["Brave API"] || creds["BRAVE_API_KEY"] || creds["api_key"];
  if (!apiKey) throw new Error("Brave Search API key not found in tool credentials");

  const query = encodeURIComponent(input);
  const url = `https://api.search.brave.com/res/v1/web/search?q=${query}&count=5`;
  const resp = await fetch(url, {
    headers: {
      "Accept": "application/json",
      "Accept-Encoding": "gzip",
      "X-Subscription-Token": apiKey,
    },
  });

  if (!resp.ok) {
    throw new Error(`Brave Search API returned ${resp.status}: ${resp.statusText}`);
  }

  const data = await resp.json() as any;
  const results = data.web?.results || [];
  if (results.length === 0) return "No search results found.";

  const formatted = results.slice(0, 5).map((r: any, i: number) => {
    const title = r.title || "Untitled";
    const url = r.url || "";
    const desc = (r.description || "").replace(/<[^>]*>/g, "").slice(0, 300);
    return `${i + 1}. **${title}**\n   URL: ${url}\n   ${desc}`;
  }).join("\n\n");

  return `## Brave Search Results for: "${input}"\n\n${formatted}`;
}

async function executeApiTool(tool: Tool, input: string): Promise<string> {
  const config = (tool.executionConfig || tool.config || {}) as Record<string, any>;
  const creds = getCredentials(tool);
  const baseUrl = config.baseUrl || config.url;
  if (!baseUrl) return `API tool "${tool.name}" has no configured endpoint URL. Input received: ${input}`;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (creds["api_key"]) headers["Authorization"] = `Bearer ${creds["api_key"]}`;

  const resp = await fetch(baseUrl, {
    method: config.method || "POST",
    headers,
    body: JSON.stringify({ input, query: input }),
  });
  const text = await resp.text();
  return text.slice(0, 4000);
}

async function executeSkillTool(tool: Tool, input: string): Promise<string> {
  if (tool.slug === "brave-search") {
    return executeBraveSearch(tool, input);
  }

  const content = tool.skillContent || tool.sourceCode || "";
  if (!content) {
    return `Skill "${tool.name}" has no executable content. The skill description is: ${tool.description || "N/A"}. Input: ${input}`;
  }

  return `## Skill: ${tool.name}\n\nSkill content loaded for context:\n${content.slice(0, 2000)}\n\nInput: ${input}\n\nNote: This skill operates in prompt_injection mode — its content has been injected into the execution context.`;
}

async function executeCliTool(tool: Tool, input: string): Promise<string> {
  const config = (tool.executionConfig || tool.config || {}) as Record<string, any>;
  const command = config.command || tool.entryPoint;
  if (!command) return `CLI tool "${tool.name}" has no configured command.`;
  return `CLI tool "${tool.name}" would execute: ${command} ${input}\n\nNote: Sandbox CLI execution is not yet enabled for security reasons.`;
}

async function executePythonTool(tool: Tool, input: string): Promise<string> {
  const code = tool.sourceCode;
  if (!code) return `Python tool "${tool.name}" has no source code.`;
  return `Python tool "${tool.name}" source code available (${code.length} chars).\n\nNote: Sandbox Python execution is not yet enabled. The code has been loaded as context.\n\nInput: ${input}`;
}

export async function executeTool(
  toolSlug: string,
  input: string,
  agentId: string,
  workOrderId?: string
): Promise<ToolExecResult> {
  const startTime = Date.now();
  const tool = await storage.getToolBySlug(toolSlug);
  if (!tool) {
    return { success: false, output: "", error: `Tool "${toolSlug}" not found`, toolName: toolSlug, toolSlug, durationMs: Date.now() - startTime };
  }
  if (tool.restricted) {
    return { success: false, output: "", error: `Tool "${tool.name}" is restricted: ${tool.restrictedReason || "No reason given"}`, toolName: tool.name, toolSlug: tool.slug, durationMs: Date.now() - startTime };
  }
  if (tool.status !== "active") {
    return { success: false, output: "", error: `Tool "${tool.name}" is not active (status: ${tool.status})`, toolName: tool.name, toolSlug: tool.slug, durationMs: Date.now() - startTime };
  }

  let lease: ToolLease | null = null;
  try {
    lease = await checkoutLease(tool, agentId, workOrderId);
  } catch (err: any) {
    console.error(`Failed to checkout lease for tool ${tool.slug}:`, err.message);
  }

  try {
    let output: string;
    switch (tool.type) {
      case "skill":
        output = await executeSkillTool(tool, input);
        break;
      case "api":
        output = await executeApiTool(tool, input);
        break;
      case "cli":
        output = await executeCliTool(tool, input);
        break;
      case "python_code":
        output = await executePythonTool(tool, input);
        break;
      default:
        output = `Tool type "${tool.type}" is not yet supported for execution. Tool: ${tool.name}, Input: ${input}`;
    }

    const result: ToolExecResult = {
      success: true,
      output,
      toolName: tool.name,
      toolSlug: tool.slug,
      leaseId: lease?.id,
      durationMs: Date.now() - startTime,
    };
    if (lease) await returnLease(lease, result);
    return result;
  } catch (err: any) {
    const result: ToolExecResult = {
      success: false,
      output: "",
      error: err.message,
      toolName: tool.name,
      toolSlug: tool.slug,
      leaseId: lease?.id,
      durationMs: Date.now() - startTime,
    };
    if (lease) await returnLease(lease, result);
    return result;
  }
}

export async function getAvailableToolsForAgent(subAgentId?: string): Promise<Array<{ slug: string; name: string; type: string; description: string }>> {
  const allTools = await storage.getTools();
  const activeTools = allTools.filter(t => t.status === "active" && !t.restricted);

  if (subAgentId) {
    const assigned = await storage.getSubAgentTools(subAgentId);
    if (assigned.length > 0) {
      const assignedIds = new Set(assigned.map(a => a.toolId));
      const entitledTools = activeTools.filter(t => assignedIds.has(t.id) || t.accessTier === "any");
      return entitledTools.map(t => ({
        slug: t.slug,
        name: t.name,
        type: t.type,
        description: t.description || t.skillContent?.slice(0, 100) || `${t.type} tool`,
      }));
    }
  }

  return activeTools.filter(t => t.accessTier === "any" || t.accessTier === "tier2").map(t => ({
    slug: t.slug,
    name: t.name,
    type: t.type,
    description: t.description || t.skillContent?.slice(0, 100) || `${t.type} tool`,
  }));
}
