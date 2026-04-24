from views._placeholders import render_placeholder

render_placeholder(
    title="User Management",
    subtitle="User + membership + role + per-user permission grant management.",
    deferred_to="Loop 9+",
    items=[
        "User roster scoped to the active tenant",
        "Invite / revoke membership flows",
        "Role assignment (owner / admin / operator / reviewer / viewer / agent_system)",
        "Per-user permission-grant overrides (Phase 4.1 `permission_grants` table)",
    ],
)
