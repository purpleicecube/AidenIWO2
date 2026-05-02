"""Loop Eta phase 1.2 — Worker H test suite.

Covers the two runnable handlers introduced in
`runtime.tools.data_ops`:

  - `_csv_validate`        — happy path + missing required column.
  - `_http_health_probe`   — happy path (httpx.MockTransport) +
                             SSRF blocklist (loopback IP literal).

These tests intentionally bypass the audit/registry plumbing in
`runtime.aiden_tools.execute_tool` and exercise the handlers directly
with a `None` connection. The handlers do not touch the database; the
`conn` parameter only exists to satisfy the registry contract.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from runtime.aiden_tools import ToolExecutionError
from runtime.tools.data_ops import (
    DATA_OPS_TOOLS,
    _csv_validate,
    _http_health_probe,
)

_TEST_CLIENT_ID = "00000000-0000-0000-0000-000000000001"


# ── csv_validate ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csv_validate_clean_csv() -> None:
    """A well-formed CSV with required fields present + non-empty
    cells must report ok=true with zero issues."""
    csv_text = "name,email\nAlice,a@b.com\nBob,b@c.com"
    result = await _csv_validate(
        None,  # type: ignore[arg-type]
        {"csv": csv_text, "required_fields": ["name", "email"]},
        _TEST_CLIENT_ID,
    )

    assert result["ok"] is True
    assert result["issues"] == []
    assert result["row_count"] == 2
    assert result["column_count"] == 2
    assert result["headers"] == ["name", "email"]


@pytest.mark.asyncio
async def test_csv_validate_detects_missing_required_field() -> None:
    """When a required field is not in the header row, the handler
    must surface a `missing_required_column` issue and ok=false."""
    csv_text = "name,phone\nAlice,555-1212\nBob,555-3434"
    result = await _csv_validate(
        None,  # type: ignore[arg-type]
        {"csv": csv_text, "required_fields": ["name", "email"]},
        _TEST_CLIENT_ID,
    )

    assert result["ok"] is False
    missing_issues = [
        i for i in result["issues"] if i["kind"] == "missing_required_column"
    ]
    assert len(missing_issues) == 1
    assert missing_issues[0]["column"] == "email"
    # The non-missing required field should not have generated a column issue.
    name_issues = [
        i
        for i in result["issues"]
        if i["kind"] == "missing_required_column" and i["column"] == "name"
    ]
    assert name_issues == []


# ── http_health_probe ────────────────────────────────────────────────


def _build_mock_client(handler) -> Any:
    """Return a factory that matches the `httpx.AsyncClient(...)`
    constructor signature but injects a `MockTransport` so no real
    network call is issued."""

    transport = httpx.MockTransport(handler)

    class _StubClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    return _StubClient


@pytest.mark.asyncio
async def test_http_health_probe_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 HEAD against an example.com-style URL should return
    ok=true with a non-zero latency and the original status code."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        return httpx.Response(200, headers={"content-length": "0"})

    monkeypatch.setattr(
        "runtime.tools.data_ops.httpx.AsyncClient",
        _build_mock_client(handler),
    )

    result = await _http_health_probe(
        None,  # type: ignore[arg-type]
        {"url": "https://example.com/", "timeout_seconds": 5},
        _TEST_CLIENT_ID,
    )

    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["latency_ms"] > 0
    assert result["redirect_count"] == 0
    assert result["final_url"].startswith("https://example.com")


@pytest.mark.asyncio
async def test_http_health_probe_ssrf_blocks_localhost() -> None:
    """A literal loopback IP must be rejected with
    `ToolExecutionError("ssrf_blocked", ...)` BEFORE any network call.
    No httpx mocking is necessary because the SSRF check raises
    synchronously before the client is constructed."""

    with pytest.raises(ToolExecutionError) as exc_info:
        await _http_health_probe(
            None,  # type: ignore[arg-type]
            {"url": "http://127.0.0.1/admin"},
            _TEST_CLIENT_ID,
        )

    assert exc_info.value.tool_name == "http_health_probe"
    assert exc_info.value.kind == "ssrf_blocked"
    assert "127.0.0.1" in exc_info.value.detail


# ── registry sanity ─────────────────────────────────────────────────


def test_data_ops_registry_exposes_both_handlers() -> None:
    """The convergence step folds DATA_OPS_TOOLS into the global
    TOOL_REGISTRY; this guards the registry literal so a typo on
    either tool key fails the worker's own suite first."""
    assert set(DATA_OPS_TOOLS) == {"csv_validate", "http_health_probe"}
    assert DATA_OPS_TOOLS["csv_validate"].handler is _csv_validate
    assert DATA_OPS_TOOLS["http_health_probe"].handler is _http_health_probe
