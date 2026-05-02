"""Loop Eta phase 1.1 — per-category tool registry packages.

Each sibling module exposes a `*_TOOLS: dict[str, ToolDefinition]`
registry which the convergence step (main agent) merges into
`runtime.aiden_tools.TOOL_REGISTRY`. Workers only own their own
sibling files; `aiden_tools.py` is hard-locked.
"""
