from views._placeholders import render_placeholder

render_placeholder(
    icon="🛠️",
    title="Tools",
    subtitle="MCP servers + internal capabilities available to agents.",
    deferred_to="Loop 9+",
    items=[
        "MCP server registry + per-tool authorization",
        "Internal helpers (prompt resolver, render routing)",
        "Rate-limit + quota status per tool",
        "Per-workflow tool allowlists",
    ],
)
