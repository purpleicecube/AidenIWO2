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
from typing import Any, Awaitable, Callable

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


async def execute_tool(
    conn: asyncpg.Connection,
    *,
    tool_name: str,
    args: dict[str, Any],
    client_id: str,
    actor_user_id: str,
    work_order_id: str | None = None,
) -> dict[str, Any]:
    """Execute one tool, write the audit row, return the result. Caller
    owns the surrounding transaction + decides what to do with errors."""
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise ToolNotFoundError(
            f"unknown tool: {tool_name!r}; "
            f"available: {sorted(TOOL_REGISTRY.keys())}"
        )

    try:
        result = await tool.handler(conn, dict(args or {}), client_id)
    except Exception as exc:  # noqa: BLE001
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="aiden.tool_failed",
            target_type="aiden_tool",
            target_id=tool_name,
            metadata={
                "tool_name": tool_name,
                "args": args,
                "kind": type(exc).__name__,
                "detail": str(exc)[:500],
                "work_order_id": work_order_id,
            },
        )
        raise ToolExecutionError(tool_name, type(exc).__name__, str(exc))

    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="aiden.tool_called",
        target_type="aiden_tool",
        target_id=tool_name,
        metadata={
            "tool_name": tool_name,
            "args": args,
            "result_size_chars": len(json.dumps(result, default=str)),
            "work_order_id": work_order_id,
        },
    )
    return result
