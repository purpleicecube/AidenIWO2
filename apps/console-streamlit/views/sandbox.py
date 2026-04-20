from views._placeholders import render_placeholder

render_placeholder(
    icon="🧪",
    title="Sandbox",
    subtitle="Isolated environment for testing changes without touching production data.",
    deferred_to="Loop 10+",
    items=[
        "Parallel fixture tenant (not live Klear / FFAI)",
        "Dry-run adapter dispatches with full audit trail",
        "Replay harness for stuck WOs / diagnosis scenarios",
        "Preview mode for template changes before promotion",
    ],
)
