"""Beta-2 — Aiden Tier 1 tool registry.

CODEX universal-slice locks (2026-05-01):
  - Aiden uses tools instead of hallucinating runtime state.
  - Tool execution is tenant-scoped via the same asyncpg connection
    Aiden Tier 1 invocation already holds (RLS + iwo3_app).
  - Every tool call writes one audit row (`aiden.tool_called`) so
    operators can see what Aiden looked at + when. Tool failures emit
    `aiden.tool_failed`.
  - Tool registry is a pure dict; no instance state. Each tool's
    handler returns a JSON-serialisable dict that gets injected back
    into Aiden's next turn as context.

Tools shipped in Phase 0.4.1 (foundational read-surface):
  - runtime_health        — platform health snapshot
  - work_order_counts     — WO counts by status for active tenant
  - recent_work_orders    — top-N recent WOs for active tenant

Future tools (Phase 0.4.2+, not built yet):
  - recent_handoffs / output package status
  - audit_log_recent
  - sub_agent_state (per-role enabled + last-invocation timestamp)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional

import asyncpg

from authz.audit_writer import write_audit_row


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    args_schema: dict[str, Any]  # JSON schema (informational; we don't validate yet)
    handler: Callable[
        [asyncpg.Connection, dict[str, Any], str],
        Awaitable[dict[str, Any]],
    ]
    # RBAC permission the ACTOR must hold for this tool to run.
    #
    # Review finding (2026-09-05, P1): `/aiden/chat` gates on
    # `work_order:create`, but a tool reached through it performed a
    # privileged workspace mutation with no check of its own — the same
    # action requires `workspace:write` on `POST /workspace/folders`.
    # RLS only enforces tenant membership, so it could not stand in for
    # authorization. Today every seeded role holding `work_order:create`
    # also holds `workspace:write`, so the matrix happens to close the
    # hole — but a guard that depends on a coincidence in the permission
    # table is not a guard. Read-only tools stay None.
    required_permission: Optional[str] = None


async def _actor_has_permission(
    conn: asyncpg.Connection,
    *,
    user_id: Optional[str],
    client_id: str,
    permission: str,
) -> bool:
    """Same decision inputs as `deps._load_permission_ctx` — role from
    active membership, role_permissions, then per-user allow/deny
    grants — evaluated by the shared `check_permission_decide`. No actor
    means no permission; a tool that mutates must never run unattributed.
    """
    if not user_id:
        return False
    from authz.check_permission import UserGrant, check_permission_decide

    role = await conn.fetchval(
        """
        SELECT role::text FROM client_memberships
         WHERE user_id = $1::uuid AND client_id = $2::uuid
           AND status = 'active'
         LIMIT 1
        """,
        user_id,
        client_id,
    )
    if role is None:
        return False
    role_perms = [
        r["permission_key"]
        for r in await conn.fetch(
            """
            SELECT p.permission_key
              FROM role_permissions rp
              JOIN permissions p ON p.id = rp.permission_id
             WHERE rp.role = $1::membership_role
            """,
            role,
        )
    ]
    grants = [
        UserGrant(permission_key=r["permission_key"], grant_type=r["grant_type"])
        for r in await conn.fetch(
            """
            SELECT p.permission_key, pg.grant_type::text AS grant_type
              FROM permission_grants pg
              JOIN permissions p ON p.id = pg.permission_id
             WHERE pg.user_id = $1::uuid AND pg.client_id = $2::uuid
            """,
            user_id,
            client_id,
        )
    ]
    return check_permission_decide(
        role=role,
        role_permissions=role_perms,
        user_grants=grants,
        permission=permission,
    ).allowed


# ── Tool handlers ────────────────────────────────────────────────────


async def _runtime_health(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Real platform health: DB up (we just queried it), worker tick env
    flags, sub-agent enabled count for this tenant. Doesn't lie."""
    sub_agents = await conn.fetch(
        """
        SELECT agent_role, enabled
          FROM llm_configs
         WHERE client_id = $1::uuid
         ORDER BY agent_role
        """,
        client_id,
    )
    enabled_roles = [
        r["agent_role"] for r in sub_agents if r["enabled"]
    ]
    disabled_roles = [
        r["agent_role"] for r in sub_agents if not r["enabled"]
    ]
    poll_disabled = os.environ.get("IWO3_POLL_WORKER_DISABLED", "").lower() in {
        "true",
        "1",
        "yes",
    }
    dispatch_disabled = os.environ.get(
        "IWO3_WO_DISPATCH_WORKER_DISABLED", ""
    ).lower() in {"true", "1", "yes"}
    gamma_live = os.environ.get("GAMMA_LIVE_ENABLED", "").lower() in {
        "true",
        "1",
        "yes",
    }

    return {
        "database": "reachable",  # we just queried it
        "auth_mode": os.environ.get("IWO3_AUTH_MODE", "dev_bearer"),
        "workers": {
            "poll_worker": "disabled" if poll_disabled else "running",
            "wo_dispatch_worker": (
                "disabled" if dispatch_disabled else "running"
            ),
        },
        "gamma_live_enabled": gamma_live,
        "sub_agents": {
            "enabled_count": len(enabled_roles),
            "enabled_roles": enabled_roles,
            "disabled_roles": disabled_roles,
        },
        "_note": (
            "These are the values I can read directly. Aiden cannot "
            "see process-level CPU/RAM or external API health from "
            "this surface; for that, point operators at /healthz, "
            "/readyz, or the System Health page."
        ),
    }


async def _work_order_counts(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """WO counts grouped by status for the active tenant."""
    # lint:bypass-rls-explain="conn is tenant-scoped via app.current_client_id GUC; RLS filters work_orders to active tenant transparently"
    rows = await conn.fetch(
        """
        SELECT status::text AS status, count(*)::int AS n
          FROM work_orders
         GROUP BY status
         ORDER BY status
        """
    )
    by_status: dict[str, int] = {r["status"]: int(r["n"]) for r in rows}
    total = sum(by_status.values())
    open_count = sum(
        n
        for s, n in by_status.items()
        if s in {"pending", "processing", "awaiting_operator"}
    )
    return {
        "total": total,
        "open": open_count,
        "by_status": by_status,
    }


async def _recent_work_orders(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Top-N most recent WOs for the active tenant (default 10).
    Returns title + status + created_at + correlation_id."""
    limit = int(args.get("limit", 10) or 10)
    limit = max(1, min(limit, 50))
    # lint:bypass-rls-explain="conn is tenant-scoped via app.current_client_id GUC; RLS filters work_orders to active tenant transparently"
    rows = await conn.fetch(
        """
        SELECT id::text          AS id,
               title,
               status::text      AS status,
               priority::text    AS priority,
               correlation_id,
               created_at::text  AS created_at
          FROM work_orders
         ORDER BY created_at DESC
         LIMIT $1
        """,
        limit,
    )
    return {
        "limit": limit,
        "count": len(rows),
        "work_orders": [dict(r) for r in rows],
    }


# ── Loop CAP-G CLOSEOUT Slice C — sub-agent wiring status tool ───


async def _sub_agent_wiring_status(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Live sub-agent wiring + degraded-surface matrix for the active
    tenant. Aiden uses this to answer questions like "which sub-agents
    are wired into branded chains right now?", "is 21st live or
    fallback-only?", "is Darla actually wired?" — without hallucinating.

    Computed from runtime truth (llm_configs / KNOWN_TIER_2_ROLES /
    workflow_template_steps / output_surface_routes / audit log).
    Excludes legacy seed labels (`mark`, `pm_alpha`, `agent_system`)
    per IWO3_SUBAGENT_WIRING_MATRIX_AND_STATUS_SURFACE_v0.1.0."""
    from .subagent_wiring import build_sub_agent_wiring_status  # noqa: PLC0415

    return await build_sub_agent_wiring_status(
        conn,
        client_id=client_id,
    )


# ── Registry ─────────────────────────────────────────────────────────


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "runtime_health": ToolDefinition(
        name="runtime_health",
        description=(
            "Platform health snapshot: DB reachability, worker run state "
            "(poll_worker / wo_dispatch_worker), Gamma live-render gate, "
            "sub-agent enabled counts for the active tenant. Use whenever "
            "the operator asks about system health, status, what's "
            "running, or whether something is broken. NEVER invent "
            "platform health values; always call this tool first."
        ),
        args_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_runtime_health,
    ),
    "work_order_counts": ToolDefinition(
        name="work_order_counts",
        description=(
            "Returns counts of work orders grouped by status for the "
            "active tenant: total, open (pending+processing+awaiting_operator), "
            "and full breakdown by status. Use when the operator asks "
            "how many WOs are open / pending / completed / etc."
        ),
        args_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_work_order_counts,
    ),
    "recent_work_orders": ToolDefinition(
        name="recent_work_orders",
        description=(
            "Returns the N most recent work orders for the active tenant "
            "(default 10, max 50): title, status, priority, correlation_id, "
            "created_at. Use when the operator asks what's been submitted "
            "recently, what's in flight, or to surface specific work."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                }
            },
            "additionalProperties": False,
        },
        handler=_recent_work_orders,
    ),
    "sub_agent_wiring_status": ToolDefinition(
        name="sub_agent_wiring_status",
        description=(
            "Live sub-agent wiring + degraded-surface matrix for the "
            "active tenant. Use whenever an operator asks which "
            "sub-agents are wired right now, which surfaces are "
            "degraded, whether Darla / Paul / Hank / etc. are "
            "currently part of branded chains, or whether a render "
            "surface (Stitch / Figma / 21st / PDF / DOCX) runs "
            "natively or via fallback. NEVER guess sub-agent status; "
            "always call this tool. Returns per-role rows with: "
            "role_key, display_name, layer, llm_enabled, "
            "direct_work_order_path, workflow_path, branded_chain_path, "
            "surfaces, degraded, degraded_reason, last_invoked_at, "
            "last_success_at, last_failure_at. Excludes legacy seed "
            "labels (mark, pm_alpha, agent_system)."
        ),
        args_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_sub_agent_wiring_status,
    ),
}


def render_tool_catalog() -> str:
    """Format the registry as a markdown catalog Aiden's system prompt
    embeds. Aiden picks the right tool by name + args from this list."""
    lines: list[str] = []
    for name, tool in TOOL_REGISTRY.items():
        lines.append(f"- **{name}** — {tool.description}")
        if tool.args_schema.get("properties"):
            args_summary = ", ".join(
                f"{k}: {v.get('type', 'any')}"
                for k, v in tool.args_schema["properties"].items()
            )
            lines.append(f"    Args: {{ {args_summary} }}")
        else:
            lines.append("    Args: {} (none)")
    return "\n".join(lines)


class ToolNotFoundError(Exception):
    pass


class ToolExecutionError(Exception):
    def __init__(self, tool_name: str, kind: str, detail: str) -> None:
        super().__init__(f"{tool_name} failed: {kind}: {detail}")
        self.tool_name = tool_name
        self.kind = kind
        self.detail = detail


async def check_sub_agent_tool_assignment(
    conn: asyncpg.Connection,
    *,
    llm_config_id: str,
    tool_key: str,
) -> bool:
    """Loop Eta — pre-execution authz for Tier 2 tool calls.

    Returns True only if BOTH the assignment row and the catalog row are
    enabled AND the catalog row's `runtime_status='runnable'`. Catalog
    rows with `runtime_status` of `catalog_only`, `planned`, or `legacy`
    are refused — those are not invocable from this surface in this
    loop. (MegaLoop Theta D9.2 retired the `mcp` and `skill_only`
    values in favour of pure-execution-truth vocabulary.)

    Caller (Tier 2 runtime) writes the `sub_agent.tool_unauthorized`
    audit row when this returns False; this helper has no side effects."""
    row = await conn.fetchrow(
        """
        SELECT sat.enabled               AS sat_enabled,
               tc.enabled                AS tc_enabled,
               tc.runtime_status::text   AS rt_status
          FROM sub_agent_tools sat
          JOIN tool_catalog tc ON tc.tool_key = sat.tool_key
         WHERE sat.llm_config_id = $1::uuid
           AND sat.tool_key = $2
        """,
        llm_config_id,
        tool_key,
    )
    if not row:
        return False
    return bool(
        row["sat_enabled"]
        and row["tc_enabled"]
        and row["rt_status"] == "runnable"
    )


async def execute_tool(
    conn: asyncpg.Connection,
    *,
    tool_name: str,
    args: dict[str, Any],
    client_id: str,
    actor_user_id: str,
    work_order_id: str | None = None,
    event_prefix: Literal["aiden", "sub_agent"] = "aiden",
    agent_role: Optional[str] = None,
    llm_config_id: Optional[str] = None,
    iteration_index: Optional[int] = None,
) -> dict[str, Any]:
    """Execute one tool, write the audit row, return the result. Caller
    owns the surrounding transaction + decides what to do with errors.

    `event_prefix` controls audit event naming so Tier 1 (Aiden) and
    Tier 2 (sub-agents) can both share this entry point while keeping
    `aiden.tool_*` and `sub_agent.tool_*` distinct in the audit log.
    Tier 2 callers also pass `agent_role`, `llm_config_id`, and
    `iteration_index` so audit forensics can trace which sub-agent
    made which call on which iteration of the tool-call loop."""
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise ToolNotFoundError(
            f"unknown tool: {tool_name!r}; "
            f"available: {sorted(TOOL_REGISTRY.keys())}"
        )

    failed_event = f"{event_prefix}.tool_failed"
    called_event = f"{event_prefix}.tool_called"

    # Authorization before side effects. Mirrors `require_permission_dep`
    # so a tool-mediated mutation is gated exactly as the equivalent
    # HTTP route, and emits the same `authz.denied` audit event.
    if tool.required_permission:
        allowed = await _actor_has_permission(
            conn,
            user_id=actor_user_id,
            client_id=client_id,
            permission=tool.required_permission,
        )
        if not allowed:
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor_user_id,
                event="authz.denied",
                target_type="aiden_tool",
                target_id=tool_name,
                metadata={
                    "tool_name": tool_name,
                    "permission": tool.required_permission,
                    "surface": event_prefix,
                },
            )
            raise ToolExecutionError(
                tool_name,
                "permission_denied",
                f"{tool_name} requires {tool.required_permission!r}, which "
                "this operator does not hold",
            )

    def _meta_base() -> dict[str, Any]:
        meta: dict[str, Any] = {
            "tool_name": tool_name,
            "args": args,
            "work_order_id": work_order_id,
        }
        if event_prefix == "sub_agent":
            meta["agent_role"] = agent_role
            meta["llm_config_id"] = llm_config_id
            meta["iteration_index"] = iteration_index
        return meta

    # Workspace tools create rows that need a non-null creator, and the
    # actor must come from the authenticated context — never from the
    # model. Injected into the handler's copy only, so the audit row's
    # `args` still records exactly what the LLM asked for.
    handler_args = dict(args or {})
    handler_args["_actor_user_id"] = actor_user_id or ""
    try:
        result = await tool.handler(conn, handler_args, client_id)
    except Exception as exc:  # noqa: BLE001
        meta = _meta_base()
        meta["kind"] = type(exc).__name__
        meta["detail"] = str(exc)[:500]
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event=failed_event,
            target_type="aiden_tool",
            target_id=tool_name,
            metadata=meta,
        )
        raise ToolExecutionError(tool_name, type(exc).__name__, str(exc))

    meta = _meta_base()
    meta["result_size_chars"] = len(json.dumps(result, default=str))
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event=called_event,
        target_type="aiden_tool",
        target_id=tool_name,
        metadata=meta,
    )
    return result


# Loop Eta phase 1.2 / Eta.2 wave 2 — merge per-category Tier 2 handler
# registries from `runtime/tools/*.py` into TOOL_REGISTRY. Each Worker
# (F/G/H/I) writes their own sibling module + a `*_TOOLS` dict. The
# convergence step (these imports + updates) lands at the END of the
# file so worker modules can `from runtime.aiden_tools import
# ToolDefinition, ToolExecutionError, ToolNotFoundError` without
# tripping a partially-initialised-module circular import.
from .tools.document_rendering import DOCUMENT_RENDERING_TOOLS  # noqa: E402
from .tools.search import SEARCH_TOOLS  # noqa: E402
from .tools.workspace import WORKSPACE_TOOLS  # noqa: E402
from .tools.data_ops import DATA_OPS_TOOLS  # noqa: E402
from .tools.stitch_mcp import STITCH_TOOLS  # noqa: E402

TOOL_REGISTRY.update(DOCUMENT_RENDERING_TOOLS)
TOOL_REGISTRY.update(SEARCH_TOOLS)
TOOL_REGISTRY.update(WORKSPACE_TOOLS)
TOOL_REGISTRY.update(DATA_OPS_TOOLS)
TOOL_REGISTRY.update(STITCH_TOOLS)
