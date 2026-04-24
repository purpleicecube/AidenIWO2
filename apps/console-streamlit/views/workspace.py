from views._placeholders import render_placeholder

render_placeholder(
    title="Workspace",
    subtitle="Per-operator working environment for live work orders.",
    deferred_to="Loop 9+",
    items=[
        "Currently-active WO tray + quick actions",
        "Scratch files linked to the operator session",
        "Recent artifacts + hand-offs the operator touched",
        "Pinned searches across the audit log",
    ],
)
