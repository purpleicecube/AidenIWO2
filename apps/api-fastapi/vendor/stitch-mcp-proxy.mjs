// Stitch MCP proxy — bridges @google/stitch-sdk into a stdio MCP server
// Used by IWO2's tool locker (mcpConfig.command) for runtime Stitch tool access.
// Auth: STITCH_API_KEY env var (from .env)
// Loop 33 (2026-03-29)

import { StitchProxy } from "@google/stitch-sdk";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const apiKey = process.env.STITCH_API_KEY;
if (!apiKey) {
  console.error("[stitch-mcp] STITCH_API_KEY not set");
  process.exit(1);
}

const proxy = new StitchProxy({ apiKey });
const transport = new StdioServerTransport();
await proxy.start(transport);
