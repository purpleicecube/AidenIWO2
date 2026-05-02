"""Loop Eta — Tier 2 runnable tool handler packages.

Each sibling module exports a `*_TOOLS: dict[str, ToolDefinition]` registry
that the convergence step in `runtime/aiden_tools.py` merges into the
top-level `TOOL_REGISTRY` so `execute_tool()` can dispatch to handlers
by name.

Splitting handlers across files keeps each Worker's write scope
exclusive and prevents merge-conflict thrash during the parallel
phase of Loop Eta. Convergence is import + dict-merge only;
`aiden_tools.py` itself stays hard-locked during worker phases.

Worker boundaries:

  - stitch_mcp.py        — Worker I (Stitch MCP, mandatory operational)
  - document_rendering.py — Worker F (PDF / markdown→PPTX / Gamma render)
  - search.py            — Worker G (Brave / Perplexity / DDG / web_scrape)
  - data_ops.py          — Worker H (csv_validate / http_health_probe)
"""
