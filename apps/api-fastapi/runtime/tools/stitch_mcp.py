"""Loop Eta phase 1.1 — Stitch MCP runnable handler.

Exports a single tool (`stitch_design`) that dispatches actions to the
Stitch MCP server over stdio. The convergence step merges
`STITCH_TOOLS` into `runtime.aiden_tools.TOOL_REGISTRY`; this module
does NOT modify aiden_tools (architect lock).

Configuration:
  - `STITCH_MCP_COMMAND` env var, shell-style. Required for real calls.
    Example: ``STITCH_MCP_COMMAND="node /home/virgina/VS_AIDEN_IWO2/server/stitch-mcp-proxy.mjs"``
  - `STITCH_API_KEY` env var — passed through to the spawned MCP
    server. The IWO2 proxy refuses to start without it.
  - `STITCH_MCP_TIMEOUT_S` (optional) — float seconds; default 30.

Action protocol (handler args):
    {
      "action": "<tool-name-on-server> | list_tools",
      "payload": { ...tool args... }
    }

When ``action == "list_tools"``: returns the catalog the MCP server
exposes (used by the routes/tools.py connection-test endpoint and by
sub-agents that want to discover what's available before they call).

Otherwise: forwards the call to ``session.call_tool(name=action,
arguments=payload)`` and wraps the result.

This handler does NOT write its own audit row — `runtime.aiden_tools.
execute_tool` already writes ``aiden.tool_called`` / ``sub_agent.
tool_called`` for the outer call. The session-level events
(``mcp.session_opened`` / ``mcp.session_closed``) live with the route
that owns the tenant-scoped DB connection.
"""

from __future__ import annotations

import os
import shlex
from typing import Any, Optional

import asyncpg

from runtime.aiden_tools import ToolDefinition, ToolExecutionError
from runtime.mcp_client import McpClientError, McpSession


STITCH_SERVER_NAME = "stitch"


def resolve_stitch_command() -> Optional[list[str]]:
    """Return the argv-list for the Stitch MCP server, or None when
    ``STITCH_MCP_COMMAND`` is unset. The string form is split with
    `shlex` so operators can use the natural shell quoting rules from
    the .env file.
    """
    raw = os.environ.get("STITCH_MCP_COMMAND", "").strip()
    if not raw:
        return None
    parts = shlex.split(raw)
    return parts if parts else None


def resolve_stitch_timeout_s() -> float:
    raw = os.environ.get("STITCH_MCP_TIMEOUT_S", "").strip()
    if not raw:
        return 30.0
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 30.0


def stitch_environment() -> dict[str, str]:
    """Return the env dict the MCP server inherits. We pass through the
    parent process env (so the operator's real STITCH_API_KEY flows
    through) and DO NOT inject anything else — keeping the surface
    minimal so a leaked subprocess can't smuggle credentials it
    shouldn't have."""
    return dict(os.environ)


async def open_stitch_session() -> McpSession:
    """Helper used by both the runtime handler and the
    /tools/stitch_design/test_connection endpoint.

    Raises McpClientError("config_missing", ...) when the env var is
    unset so the route can return a clean 503 instead of a generic 500.
    """
    cmd = resolve_stitch_command()
    if cmd is None:
        raise McpClientError(
            "config_missing",
            (
                "STITCH_MCP_COMMAND env var is not set. Set it to the "
                "shell command that launches the Stitch MCP stdio "
                "server (e.g. 'node /path/to/stitch-mcp-proxy.mjs') "
                "and ensure STITCH_API_KEY is exported to the runtime."
            ),
        )
    return await McpSession.open(
        server_name=STITCH_SERVER_NAME,
        command=cmd,
        env=stitch_environment(),
        timeout_s=resolve_stitch_timeout_s(),
    )


# ── Tool handler ────────────────────────────────────────────────────


async def _stitch_design(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Dispatch a Stitch MCP action.

    The `conn` + `client_id` arguments are unused at handler depth
    (Stitch MCP is tenant-agnostic) but the `aiden_tools` ToolDefinition
    contract requires them. The outer `execute_tool()` writes the
    `*.tool_called` audit row so the tenant scope is preserved at that
    layer.
    """
    action = (args or {}).get("action", "")
    payload = (args or {}).get("payload") or {}
    if not isinstance(action, str) or not action.strip():
        raise ToolExecutionError(
            "stitch_design",
            "invalid_args",
            "action is required and must be a non-empty string",
        )
    if not isinstance(payload, dict):
        raise ToolExecutionError(
            "stitch_design",
            "invalid_args",
            f"payload must be an object; got {type(payload).__name__}",
        )

    try:
        session = await open_stitch_session()
    except McpClientError as exc:
        raise ToolExecutionError(
            "stitch_design",
            f"mcp_{exc.kind}",
            str(exc),
        ) from exc

    try:
        if action == "list_tools":
            try:
                tools = await session.list_tools()
            except McpClientError as exc:
                raise ToolExecutionError(
                    "stitch_design",
                    f"mcp_{exc.kind}",
                    str(exc),
                ) from exc
            return {
                "action": "list_tools",
                "server": session.server_name,
                "tools": tools,
            }

        try:
            result = await session.call_tool(
                name=action, arguments=payload
            )
        except McpClientError as exc:
            raise ToolExecutionError(
                "stitch_design",
                f"mcp_{exc.kind}",
                str(exc),
            ) from exc
        return {
            "action": action,
            "server": session.server_name,
            "result": result,
        }
    finally:
        await session.close()


# ── Registry export ──────────────────────────────────────────────────


STITCH_TOOLS: dict[str, ToolDefinition] = {
    "stitch_design": ToolDefinition(
        name="stitch_design",
        description=(
            "Dispatch a design action to the Stitch MCP server. "
            "Set action='list_tools' to enumerate the MCP server's "
            "tool catalog (use this first when you don't know what's "
            "available). Set action='<tool-name>' + payload={...} to "
            "invoke a specific Stitch tool. Routed via "
            "STITCH_MCP_COMMAND stdio MCP proxy."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "Stitch MCP tool name, or 'list_tools' to "
                        "enumerate available tools."
                    ),
                },
                "payload": {
                    "type": "object",
                    "description": (
                        "Tool-specific arguments. Required, may be "
                        "empty for 'list_tools'."
                    ),
                },
            },
            "required": ["action", "payload"],
            "additionalProperties": False,
        },
        handler=_stitch_design,
    ),
}
