"""Loop Eta phase 1.1 — runtime tool surface routes.

Phase 1.1 ships only ``GET /tools/stitch_design/test_connection`` so
operators can verify the Stitch MCP wiring (auth ok, server reachable,
tool catalog enumerable) before any sub-agent attempts a real call.

Future endpoints (deferred): per-tool diagnostics for the other Eta.2
runnable handlers (e.g. /tools/web_search_brave/test_connection).

Audit:
  - ``mcp.session_opened`` on each successful open (one per call)
  - ``mcp.session_closed`` on each close
  - ``mcp.connection_tested`` always — success OR fail — so operators
    can tell from the audit log whether the test ran
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from authz.audit_writer import write_audit_row
from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)
from runtime.mcp_client import McpClientError, McpSession
from runtime.tools.stitch_mcp import (
    STITCH_SERVER_NAME,
    open_stitch_session,
    resolve_stitch_command,
)


router = APIRouter(prefix="/tools", tags=["tools"])


class StitchTestConnectionResponse(BaseModel):
    ok: bool
    server_name: str
    tool_count: Optional[int] = None
    latency_ms: Optional[int] = None
    sample_tool_names: list[str] = []
    error: Optional[str] = None
    kind: Optional[str] = None
    command_resolved: bool = False


async def _audit_session_opened(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: str,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="mcp.session_opened",
        target_type="mcp_server",
        target_id=STITCH_SERVER_NAME,
        metadata={"server_name": STITCH_SERVER_NAME},
    )


async def _audit_session_closed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: str,
    duration_ms: int,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="mcp.session_closed",
        target_type="mcp_server",
        target_id=STITCH_SERVER_NAME,
        metadata={
            "server_name": STITCH_SERVER_NAME,
            "duration_ms": duration_ms,
        },
    )


async def _audit_connection_tested(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: str,
    ok: bool,
    tool_count: Optional[int],
    latency_ms: int,
    error: Optional[str],
    kind: Optional[str],
) -> None:
    md: dict[str, Any] = {
        "server_name": STITCH_SERVER_NAME,
        "ok": ok,
        "latency_ms": latency_ms,
    }
    if tool_count is not None:
        md["tool_count"] = tool_count
    if error is not None:
        md["error"] = error[:500]
    if kind is not None:
        md["kind"] = kind
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="mcp.connection_tested",
        target_type="mcp_server",
        target_id=STITCH_SERVER_NAME,
        metadata=md,
    )


@router.get(
    "/stitch_design/test_connection",
    dependencies=[Depends(require_permission_dep("tool_catalog:read"))],
)
async def test_stitch_connection(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> JSONResponse:
    """Open a Stitch MCP session, enumerate tools, close, audit, return.

    On any failure: returns 503 with ``{ok: false, error, kind}``.
    Never raises 500 — operators rely on the JSON body to diagnose
    config gaps (STITCH_MCP_COMMAND unset, key missing, server crash,
    etc.) without grepping logs.
    """
    started = time.monotonic()
    cmd_resolved = resolve_stitch_command() is not None

    session: Optional[McpSession] = None
    try:
        session = await open_stitch_session()
    except McpClientError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        await _audit_connection_tested(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            ok=False,
            tool_count=None,
            latency_ms=elapsed_ms,
            error=exc.detail,
            kind=exc.kind,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=StitchTestConnectionResponse(
                ok=False,
                server_name=STITCH_SERVER_NAME,
                tool_count=None,
                latency_ms=elapsed_ms,
                error=exc.detail,
                kind=exc.kind,
                command_resolved=cmd_resolved,
            ).model_dump(),
        )

    await _audit_session_opened(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
    )
    try:
        try:
            tools = await session.list_tools()
        except McpClientError as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            await _audit_connection_tested(
                conn,
                client_id=ctx["client_id"],
                actor_user_id=ctx["user_id"],
                ok=False,
                tool_count=None,
                latency_ms=elapsed_ms,
                error=exc.detail,
                kind=exc.kind,
            )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=StitchTestConnectionResponse(
                    ok=False,
                    server_name=STITCH_SERVER_NAME,
                    tool_count=None,
                    latency_ms=elapsed_ms,
                    error=exc.detail,
                    kind=exc.kind,
                    command_resolved=cmd_resolved,
                ).model_dump(),
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        sample_names = [t.get("name", "") for t in tools[:5] if t.get("name")]
        await _audit_connection_tested(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            ok=True,
            tool_count=len(tools),
            latency_ms=elapsed_ms,
            error=None,
            kind=None,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=StitchTestConnectionResponse(
                ok=True,
                server_name=STITCH_SERVER_NAME,
                tool_count=len(tools),
                latency_ms=elapsed_ms,
                sample_tool_names=sample_names,
                command_resolved=cmd_resolved,
            ).model_dump(),
        )
    finally:
        close_started = time.monotonic()
        try:
            await session.close()
        except Exception:  # noqa: BLE001
            # close errors are absorbed; the wrapper logs internally
            pass
        await _audit_session_closed(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            duration_ms=int((time.monotonic() - close_started) * 1000),
        )
