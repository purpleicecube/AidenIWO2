import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";

export interface McpConfig {
  serverName?: string;
  transport: "stdio" | "sse";
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  tools?: string[];
  resources?: string[];
}

export interface McpToolInfo {
  name: string;
  description: string;
  inputSchema?: Record<string, any>;
}

export interface McpCallResult {
  success: boolean;
  output: string;
  error?: string;
  toolName: string;
  serverName: string;
}

const MCP_TIMEOUT_MS = 30000;

function parseConfig(raw: any): McpConfig {
  if (!raw || typeof raw !== "object") {
    throw new Error("Invalid MCP config: must be a non-null object");
  }
  const transport = raw.transport || "stdio";
  if (transport !== "stdio" && transport !== "sse") {
    throw new Error(`Invalid MCP transport: "${transport}" — must be "stdio" or "sse"`);
  }
  if (transport === "stdio" && !raw.command) {
    throw new Error("MCP stdio transport requires a 'command' field");
  }
  if (transport === "sse" && !raw.url) {
    throw new Error("MCP SSE transport requires a 'url' field");
  }
  return {
    serverName: raw.serverName || "mcp-server",
    transport,
    command: raw.command,
    args: Array.isArray(raw.args) ? raw.args : (typeof raw.args === "string" ? raw.args.split(",").map((a: string) => a.trim()).filter(Boolean) : []),
    env: raw.env || {},
    url: raw.url,
    tools: Array.isArray(raw.tools) ? raw.tools : [],
    resources: Array.isArray(raw.resources) ? raw.resources : [],
  };
}

function resolveEnvVars(env: Record<string, string>): Record<string, string> {
  const resolved: Record<string, string> = {};
  for (const [key, value] of Object.entries(env)) {
    if (typeof value === "string" && value.startsWith("env:")) {
      const envVarName = value.slice(4);
      resolved[key] = process.env[envVarName] || "";
    } else {
      resolved[key] = value;
    }
  }
  return resolved;
}

async function createTransport(config: McpConfig) {
  if (config.transport === "stdio") {
    const resolvedEnv = resolveEnvVars(config.env || {});
    return new StdioClientTransport({
      command: config.command!,
      args: config.args || [],
      env: { ...process.env, ...resolvedEnv } as Record<string, string>,
    });
  } else {
    const url = new URL(config.url!);
    return new SSEClientTransport(url);
  }
}

async function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`MCP ${label} timed out after ${ms}ms`)), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer!);
  }
}

async function createClient(config: McpConfig): Promise<Client> {
  const transport = await createTransport(config);
  const client = new Client(
    { name: "aiden-iwo", version: "0.9.5" },
    { capabilities: {} }
  );
  await withTimeout(client.connect(transport), MCP_TIMEOUT_MS, "connection");
  return client;
}

export async function connectAndListTools(rawConfig: any): Promise<{ tools: McpToolInfo[]; serverName: string }> {
  const config = parseConfig(rawConfig);
  const client = await createClient(config);

  try {
    const response = await withTimeout(
      client.listTools(),
      MCP_TIMEOUT_MS,
      "listTools"
    );

    const tools: McpToolInfo[] = (response.tools || []).map((t: any) => ({
      name: t.name,
      description: t.description || "",
      inputSchema: t.inputSchema || {},
    }));

    return { tools, serverName: config.serverName || "mcp-server" };
  } finally {
    try { await client.close(); } catch {}
  }
}

export async function connectAndCallTool(
  rawConfig: any,
  toolName: string,
  args: Record<string, any>
): Promise<McpCallResult> {
  const config = parseConfig(rawConfig);
  const serverName = config.serverName || "mcp-server";
  const client = await createClient(config);

  try {
    const response = await withTimeout(
      client.callTool({ name: toolName, arguments: args }),
      MCP_TIMEOUT_MS,
      `callTool(${toolName})`
    );

    const contentParts = (response.content || []) as any[];
    const output = contentParts.map((part: any) => {
      if (part.type === "text") return part.text;
      if (part.type === "image") return `[Image: ${part.mimeType || "image"}, ${(part.data?.length || 0)} bytes]`;
      if (part.type === "resource") return `[Resource: ${part.uri || "unknown"}]`;
      return JSON.stringify(part);
    }).join("\n");

    return {
      success: !response.isError,
      output: output || "(empty response)",
      error: response.isError ? output : undefined,
      toolName,
      serverName,
    };
  } finally {
    try { await client.close(); } catch {}
  }
}

export async function testConnection(rawConfig: any): Promise<{ success: boolean; message: string; tools: McpToolInfo[] }> {
  try {
    const { tools, serverName } = await connectAndListTools(rawConfig);
    return {
      success: true,
      message: `Connected to "${serverName}" — ${tools.length} tool(s) available: ${tools.map(t => t.name).join(", ") || "(none)"}`,
      tools,
    };
  } catch (err: any) {
    return {
      success: false,
      message: `Connection failed: ${err.message}`,
      tools: [],
    };
  }
}
