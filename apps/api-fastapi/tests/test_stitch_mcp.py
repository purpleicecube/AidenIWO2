"""Loop Eta phase 1.1 — Stitch MCP runnable handler tests.

Three smoke tests that satisfy Worker I's exit gate without burning
real Stitch credits:

  1. test_stitch_handler_registered — STITCH_TOOLS exposes a
     correctly-shaped ToolDefinition for stitch_design.

  2. test_stitch_connection_endpoint_returns_tool_count — the FastAPI
     route /tools/stitch_design/test_connection returns 200 + tool_count
     when the MCP session is mocked. Skipped when no IWO3_DATABASE_URL
     is set (the route depends on tenant-scoped DB).

  3. test_stitch_round_trip_via_handler — _stitch_design forwards the
     args correctly to McpSession.call_tool and wraps the result.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str = KLEAR_OWNER) -> dict[str, str]:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


# ── 1. Handler is in the registry with the correct shape ────────────


def test_stitch_handler_registered() -> None:
    """STITCH_TOOLS must expose `stitch_design` with the
    {action, payload} args_schema and a callable handler."""
    from runtime.tools.stitch_mcp import STITCH_TOOLS, _stitch_design
    from runtime.aiden_tools import ToolDefinition

    assert "stitch_design" in STITCH_TOOLS, (
        "stitch_design must be exported from STITCH_TOOLS so the "
        "convergence step can merge it into TOOL_REGISTRY"
    )
    tool = STITCH_TOOLS["stitch_design"]
    assert isinstance(tool, ToolDefinition)
    assert tool.name == "stitch_design"
    assert callable(tool.handler)
    # Args schema parity with the seed row + ETA scope §4.
    schema = tool.args_schema
    assert schema.get("type") == "object"
    props = schema.get("properties", {})
    assert "action" in props and props["action"]["type"] == "string"
    assert "payload" in props and props["payload"]["type"] == "object"
    required = set(schema.get("required", []))
    assert {"action", "payload"}.issubset(required)
    # Handler reference must be the same callable we imported (no
    # accidental rebinding).
    assert tool.handler is _stitch_design


# ── 2. Test_connection endpoint returns tool_count under a mock MCP ─


@iwo3_db
def test_stitch_connection_endpoint_returns_tool_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock McpSession.open + list_tools so the route can return 200 +
    tool_count without spawning a real subprocess. Validates the audit
    write path + response shape."""
    from fastapi.testclient import TestClient

    fake_session = MagicMock()
    fake_session.server_name = "stitch"
    fake_session.list_tools = AsyncMock(
        return_value=[
            {"name": "stitch.design", "description": "design", "inputSchema": {}},
            {"name": "stitch.refine", "description": "refine", "inputSchema": {}},
        ]
    )
    fake_session.close = AsyncMock(return_value=None)

    async def _fake_open(**_kwargs: Any) -> Any:
        return fake_session

    # Patch the helper the route imports — `routes.tools.open_stitch_session`
    # — not the module-internal alias inside runtime.tools.stitch_mcp.
    monkeypatch.setattr(
        "routes.tools.open_stitch_session", _fake_open
    )
    # And ensure the `command_resolved` flag doesn't lie when the env
    # var is unset (the route reports True when STITCH_MCP_COMMAND is
    # set; we don't care what value, just that it's truthy).
    monkeypatch.setenv("STITCH_MCP_COMMAND", "node /tmp/fake-stitch.mjs")

    # Re-import main after env var is set to honour the test posture.
    from main import app

    with TestClient(app) as client:
        r = client.get(
            "/tools/stitch_design/test_connection",
            headers=_hdr(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["server_name"] == "stitch"
    assert body["tool_count"] == 2
    assert body["sample_tool_names"] == ["stitch.design", "stitch.refine"]
    assert body["command_resolved"] is True
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0
    assert body.get("error") is None
    fake_session.list_tools.assert_awaited_once()
    fake_session.close.assert_awaited()


# ── 3. Round-trip via the handler with a mocked McpSession ──────────


def test_stitch_round_trip_via_handler() -> None:
    """_stitch_design must forward action/payload into
    session.call_tool(name=..., arguments=...) and wrap the response."""
    from runtime.tools import stitch_mcp as mod

    fake_session = MagicMock()
    fake_session.server_name = "stitch"
    fake_session.call_tool = AsyncMock(
        return_value={
            "tool": "stitch.design",
            "success": True,
            "output": "ok",
            "raw_content": [{"type": "text", "text": "ok"}],
        }
    )
    fake_session.close = AsyncMock(return_value=None)

    async def _fake_open() -> Any:
        return fake_session

    fake_conn = MagicMock()  # handler doesn't use it for stitch

    async def _run() -> dict[str, Any]:
        with patch.object(mod, "open_stitch_session", _fake_open):
            return await mod._stitch_design(
                fake_conn,
                {"action": "stitch.design", "payload": {"x": 1, "y": "z"}},
                "client-id",
            )

    result = asyncio.run(_run())
    assert result["action"] == "stitch.design"
    assert result["server"] == "stitch"
    assert result["result"]["success"] is True
    assert result["result"]["output"] == "ok"
    fake_session.call_tool.assert_awaited_once_with(
        name="stitch.design", arguments={"x": 1, "y": "z"}
    )
    fake_session.close.assert_awaited_once()


def test_stitch_handler_list_tools_action() -> None:
    """When action='list_tools', the handler must call
    session.list_tools() (NOT call_tool) and return the catalog."""
    from runtime.tools import stitch_mcp as mod

    fake_session = MagicMock()
    fake_session.server_name = "stitch"
    fake_session.list_tools = AsyncMock(
        return_value=[
            {"name": "stitch.design", "description": "", "inputSchema": {}}
        ]
    )
    fake_session.call_tool = AsyncMock()  # must NOT be called
    fake_session.close = AsyncMock(return_value=None)

    async def _fake_open() -> Any:
        return fake_session

    fake_conn = MagicMock()

    async def _run() -> dict[str, Any]:
        with patch.object(mod, "open_stitch_session", _fake_open):
            return await mod._stitch_design(
                fake_conn,
                {"action": "list_tools", "payload": {}},
                "client-id",
            )

    result = asyncio.run(_run())
    assert result["action"] == "list_tools"
    assert result["server"] == "stitch"
    assert len(result["tools"]) == 1
    fake_session.list_tools.assert_awaited_once()
    fake_session.call_tool.assert_not_awaited()


def test_stitch_handler_rejects_invalid_args() -> None:
    """Empty action or non-dict payload should raise ToolExecutionError
    BEFORE any MCP call is made (no session spawn, no credits burned)."""
    from runtime.aiden_tools import ToolExecutionError
    from runtime.tools import stitch_mcp as mod

    fake_open_called = False

    async def _fake_open() -> Any:
        nonlocal fake_open_called
        fake_open_called = True
        return MagicMock()

    fake_conn = MagicMock()

    async def _run_empty_action() -> Any:
        with patch.object(mod, "open_stitch_session", _fake_open):
            return await mod._stitch_design(
                fake_conn, {"action": "", "payload": {}}, "c"
            )

    async def _run_bad_payload() -> Any:
        with patch.object(mod, "open_stitch_session", _fake_open):
            return await mod._stitch_design(
                fake_conn,
                {"action": "x", "payload": "not-a-dict"},
                "c",
            )

    with pytest.raises(ToolExecutionError):
        asyncio.run(_run_empty_action())
    with pytest.raises(ToolExecutionError):
        asyncio.run(_run_bad_payload())
    assert fake_open_called is False, (
        "validation must short-circuit before spawning the MCP server"
    )
