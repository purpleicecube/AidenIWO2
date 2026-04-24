from views._placeholders import render_placeholder

render_placeholder(
    title="Aiden Settings",
    subtitle="Tier-1 policy + routing + decision configuration per tenant.",
    deferred_to="Loop 9+",
    items=[
        "Prompt profile selection + style override defaults",
        "Routing thresholds (explicit WO vs WF vs clarification)",
        "Approval-gate defaults per tenant",
        "Candidate-review fallback policy",
    ],
)
