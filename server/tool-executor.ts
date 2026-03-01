import { storage } from "./storage";
import type { Tool, ToolLease } from "@shared/schema";
import { connectAndListTools, connectAndCallTool } from "./mcp-client";

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

async function executeWebScraper(input: string): Promise<string> {
  const urls = input.match(/https?:\/\/[^\s,\n]+/g);
  if (!urls || urls.length === 0) {
    return `No valid URLs found in input. Provide one or more URLs to scrape. Input received: ${input}`;
  }

  const results: string[] = [];
  for (const url of urls.slice(0, 5)) {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      const resp = await fetch(url, {
        headers: {
          "User-Agent": "Mozilla/5.0 (compatible; AidenBot/1.0; +https://aiden-iwo.replit.app)",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        signal: controller.signal,
        redirect: "follow",
      });
      clearTimeout(timeout);

      if (!resp.ok) {
        results.push(`## ${url}\nHTTP ${resp.status} ${resp.statusText}`);
        continue;
      }

      const html = await resp.text();
      const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
      const title = titleMatch ? titleMatch[1].replace(/\s+/g, " ").trim() : "No title";
      const metaDescMatch = html.match(/<meta[^>]*name=["']description["'][^>]*content=["']([^"']+)["']/i)
        || html.match(/<meta[^>]*content=["']([^"']+)["'][^>]*name=["']description["']/i);
      const metaDesc = metaDescMatch ? metaDescMatch[1].trim() : "";

      let text = html
        .replace(/<script[\s\S]*?<\/script>/gi, "")
        .replace(/<style[\s\S]*?<\/style>/gi, "")
        .replace(/<nav[\s\S]*?<\/nav>/gi, "")
        .replace(/<footer[\s\S]*?<\/footer>/gi, "")
        .replace(/<header[\s\S]*?<\/header>/gi, " [HEADER] ")
        .replace(/<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/gi, "\n## $1\n")
        .replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, "- $1\n")
        .replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, "$1\n\n")
        .replace(/<a[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi, "[$2]($1)")
        .replace(/<br\s*\/?>/gi, "\n")
        .replace(/<[^>]+>/g, " ")
        .replace(/&nbsp;/g, " ")
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/\n{3,}/g, "\n\n")
        .replace(/[ \t]+/g, " ")
        .trim();

      text = text.slice(0, 6000);
      results.push(`## ${url}\n**Title:** ${title}\n${metaDesc ? `**Description:** ${metaDesc}\n` : ""}\n**Content:**\n${text}`);
    } catch (err: any) {
      results.push(`## ${url}\nFetch failed: ${err.message}`);
    }
  }
  return results.join("\n\n---\n\n");
}

async function executeHealthCheck(input: string): Promise<string> {
  const urls = input.match(/https?:\/\/[^\s,\n]+/g);
  if (!urls || urls.length === 0) {
    return `No valid URLs found. Provide URLs to health-check. Input: ${input}`;
  }
  const results: string[] = [];
  for (const url of urls.slice(0, 10)) {
    const start = Date.now();
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      const resp = await fetch(url, { method: "HEAD", signal: controller.signal, redirect: "follow" });
      clearTimeout(timeout);
      const latency = Date.now() - start;
      results.push(`${url} — ${resp.ok ? "UP" : "DOWN"} (HTTP ${resp.status}, ${latency}ms)`);
    } catch (err: any) {
      const latency = Date.now() - start;
      results.push(`${url} — DOWN (${err.message}, ${latency}ms)`);
    }
  }
  return `## Health Check Results\n\n${results.join("\n")}`;
}

async function executeDataValidator(input: string): Promise<string> {
  const lines = input.trim().split("\n");
  if (lines.length < 2) {
    return `Data validation requires at least a header row and one data row (CSV format). Received ${lines.length} line(s).\n\nInput:\n${input}`;
  }
  const headers = lines[0].split(",").map(h => h.trim().replace(/^"|"$/g, ""));
  const rows: Record<string, string>[] = [];
  const issues: string[] = [];
  for (let i = 1; i < lines.length; i++) {
    const vals = lines[i].match(/("(?:[^"\\]|\\.)*"|[^,]*)/g) || [];
    const row: Record<string, string> = {};
    headers.forEach((h, j) => { row[h] = (vals[j] || "").trim().replace(/^"|"$/g, ""); });
    if (Object.values(row).every(v => !v)) {
      issues.push(`Row ${i}: all fields empty`);
      continue;
    }
    for (const [key, val] of Object.entries(row)) {
      if (!val) issues.push(`Row ${i}: missing "${key}"`);
    }
    rows.push(row);
  }
  return `## Data Validation Report\n\n**Columns:** ${headers.join(", ")}\n**Rows parsed:** ${rows.length}\n**Issues found:** ${issues.length}\n${issues.length > 0 ? `\n### Issues\n${issues.map(i => `- ${i}`).join("\n")}` : "\nAll rows valid."}\n\n### Sample Data (first 5 rows)\n${rows.slice(0, 5).map((r, i) => `**Row ${i + 1}:** ${JSON.stringify(r)}`).join("\n")}`;
}

async function executeSkillTool(tool: Tool, input: string): Promise<string> {
  if (tool.slug === "brave-search") {
    return executeBraveSearch(tool, input);
  }
  if (tool.slug === "webscrapper") {
    return executeWebScraper(input);
  }
  if (tool.slug === "pdf-processor") {
    return executePdfProcessor(input);
  }

  const content = tool.skillContent || tool.sourceCode || "";
  if (!content) {
    return `Skill "${tool.name}" has no executable content. The skill description is: ${tool.description || "N/A"}. Input: ${input}`;
  }

  return `## Skill: ${tool.name}\n\nSkill content loaded for context:\n${content.slice(0, 2000)}\n\nInput: ${input}\n\nNote: This skill operates in prompt_injection mode — its content has been injected into the execution context.`;
}

async function executePdfProcessor(input: string): Promise<string> {
  const urls = input.match(/https?:\/\/[^\s,\n]+\.pdf/gi);
  if (urls && urls.length > 0) {
    const results: string[] = [];
    for (const url of urls.slice(0, 3)) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        const resp = await fetch(url, { signal: controller.signal });
        clearTimeout(timeout);
        if (!resp.ok) {
          results.push(`${url} — HTTP ${resp.status}`);
          continue;
        }
        const buf = await resp.arrayBuffer();
        const text = Buffer.from(buf).toString("utf-8").replace(/[^\x20-\x7E\n\r\t]/g, " ").replace(/\s{3,}/g, " ").trim();
        results.push(`## PDF: ${url}\n**Size:** ${buf.byteLength} bytes\n**Extracted text (first 4000 chars):**\n${text.slice(0, 4000)}`);
      } catch (err: any) {
        results.push(`${url} — Fetch failed: ${err.message}`);
      }
    }
    return results.join("\n\n---\n\n");
  }
  return `PDF Processor: No PDF URLs found in input. Provide URLs ending in .pdf to extract text.\n\nInput: ${input}`;
}

async function executeCliTool(tool: Tool, input: string): Promise<string> {
  if (tool.slug === "health-check-cli") {
    return executeHealthCheck(input);
  }
  const config = (tool.executionConfig || tool.config || {}) as Record<string, any>;
  const command = config.command || tool.entryPoint;
  if (!command) return `CLI tool "${tool.name}" has no configured command.`;
  return `CLI tool "${tool.name}" would execute: ${command} ${input}\n\nNote: Sandbox CLI execution is not yet enabled for security reasons.`;
}

async function executePythonTool(tool: Tool, input: string): Promise<string> {
  if (tool.slug === "data-validator") {
    return executeDataValidator(input);
  }
  const code = tool.sourceCode;
  if (!code) return `Python tool "${tool.name}" has no source code.`;
  return `Python tool "${tool.name}" source code available (${code.length} chars).\n\nNote: Sandbox Python execution is not yet enabled. The code has been loaded as context.\n\nInput: ${input}`;
}

async function executeMcpTool(tool: Tool, input: string): Promise<string> {
  const mcpConfig = tool.mcpConfig as any;
  if (!mcpConfig || (typeof mcpConfig === "object" && Object.keys(mcpConfig).length === 0)) {
    return `MCP tool "${tool.name}" has no MCP configuration. Configure transport, command/URL, and other settings.`;
  }

  let targetToolName: string | null = null;
  let toolArgs: Record<string, any> = {};

  const toolNameMatch = input.match(/^toolName:\s*(.+?)(?:\n|$)/i);
  const argsMatch = input.match(/^args:\s*(.+)/im);

  if (toolNameMatch) {
    targetToolName = toolNameMatch[1].trim();
    if (argsMatch) {
      try {
        toolArgs = JSON.parse(argsMatch[1].trim());
      } catch {
        toolArgs = { query: argsMatch[1].trim() };
      }
    }
  } else {
    const jsonMatch = input.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[0]);
        targetToolName = parsed.toolName || parsed.tool || parsed.name || null;
        toolArgs = parsed.args || parsed.arguments || parsed.input || {};
        if (typeof toolArgs === "string") toolArgs = { query: toolArgs };
      } catch {}
    }
  }

  if (!targetToolName) {
    try {
      const { tools, serverName } = await connectAndListTools(mcpConfig);
      if (tools.length === 0) {
        return `MCP server "${serverName}" connected but exposes no tools.`;
      }
      const listing = tools.map((t, i) => {
        const schema = t.inputSchema ? `\n     Input: ${JSON.stringify(t.inputSchema)}` : "";
        return `  ${i + 1}. ${t.name} — ${t.description || "No description"}${schema}`;
      }).join("\n");
      return `## MCP Server: ${serverName}\n\nAvailable tools:\n${listing}\n\nTo call a tool, use format:\ntoolName: <name>\nargs: {"key": "value"}`;
    } catch (err: any) {
      return `MCP tool discovery failed for "${tool.name}": ${err.message}`;
    }
  }

  try {
    const result = await connectAndCallTool(mcpConfig, targetToolName, toolArgs);
    if (result.success) {
      return `## MCP Tool Result: ${result.toolName} (via ${result.serverName})\n\n${result.output}`;
    } else {
      return `MCP tool "${result.toolName}" returned error: ${result.error || result.output}`;
    }
  } catch (err: any) {
    return `MCP tool execution failed for "${targetToolName}" on "${tool.name}": ${err.message}`;
  }
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
      case "mcp_server":
        output = await executeMcpTool(tool, input);
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
      const enabledIds = new Set(assigned.filter(a => a.enabled !== false).map(a => a.toolId));
      const disabledIds = new Set(assigned.filter(a => a.enabled === false).map(a => a.toolId));
      const entitledTools = activeTools.filter(t => !disabledIds.has(t.id) && (enabledIds.has(t.id) || t.accessTier === "any" || t.accessTier === "tier2"));
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
