"""Loop Eta phase 1.1 — minimal Python MCP stdio-session wrapper.

Bridges the official `mcp` Python SDK into the IWO3 runtime. The shape
mirrors IWO2's `server/mcp-client.ts` (StdioClientTransport + Client +
listTools/callTool with timeouts) but is single-process and async-only.

Design notes:
  - Each `McpSession.open(...)` spawns the configured stdio server,
    completes the MCP `initialize` handshake, and returns a session
    whose lifetime the caller manages explicitly via `close()`.
  - The session object is NOT thread-safe. FastAPI runs on a single
    uvloop event loop, so concurrent calls into one session would
    interleave on the underlying stream. Callers either (a) use
    short-lived "open → call → close" pairs (current pattern in
    `_stitch_design`) or (b) wrap shared sessions in an `asyncio.Lock`.
  - `session_opened` and `session_closed` audit events fire from the
    caller, not the wrapper, because the wrapper has no DB connection
    and the audit event needs to live inside the tenant transaction.
    The wrapper records timing + outcome so the caller can fill the
    metadata it owns.
  - All long-running primitives (open, list_tools, call_tool, close)
    are wrapped in `asyncio.wait_for` with a default 30s timeout —
    matches IWO2's `MCP_TIMEOUT_MS`. Timeouts surface as
    `McpClientError(kind="timeout")`.

This module deliberately does NOT call `aiden_tools` or `write_audit_row`.
That keeps it import-safe from non-DB contexts (CLI smoke, tests with
mocks) and lets the architect-locked `aiden_tools.py` stay untouched.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


log = logging.getLogger("iwo3.mcp_client")

DEFAULT_TIMEOUT_S: float = 30.0


class McpClientError(Exception):
    """Raised by McpSession when an MCP operation fails. `kind` is one
    of: "spawn_failed" | "handshake_failed" | "timeout" |
    "list_tools_failed" | "call_tool_failed" | "closed"."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class McpSession:
    """Pooled-style stdio MCP session wrapper.

    Open once per server (`McpSession.open(...)`), call `list_tools()`
    and/or `call_tool()` as many times as needed, then `close()`.
    """

    def __init__(
        self,
        *,
        server_name: str,
        command: list[str],
        env: Optional[dict[str, str]] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if not command:
            raise ValueError("command must be a non-empty list")
        self.server_name = server_name
        self._command = list(command)
        self._env = dict(env) if env else None
        self._timeout_s = float(timeout_s)
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._opened_at: Optional[float] = None
        self._closed: bool = False

    @classmethod
    async def open(
        cls,
        *,
        server_name: str,
        command: list[str],
        env: Optional[dict[str, str]] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> "McpSession":
        """Spawn the stdio MCP server and complete the initialize
        handshake. Raises McpClientError on spawn or handshake failure.
        """
        sess = cls(
            server_name=server_name,
            command=command,
            env=env,
            timeout_s=timeout_s,
        )
        await sess._open_internal()
        return sess

    async def _open_internal(self) -> None:
        head, *rest = self._command
        params = StdioServerParameters(
            command=head,
            args=rest,
            env=self._env,
        )
        stack = AsyncExitStack()
        try:
            try:
                read, write = await asyncio.wait_for(
                    stack.enter_async_context(stdio_client(params)),
                    timeout=self._timeout_s,
                )
            except asyncio.TimeoutError as exc:
                await stack.aclose()
                raise McpClientError(
                    "timeout",
                    f"stdio_client(open) exceeded {self._timeout_s}s",
                ) from exc
            except Exception as exc:  # noqa: BLE001
                await stack.aclose()
                raise McpClientError("spawn_failed", str(exc)) from exc

            try:
                session = await asyncio.wait_for(
                    stack.enter_async_context(ClientSession(read, write)),
                    timeout=self._timeout_s,
                )
                await asyncio.wait_for(
                    session.initialize(), timeout=self._timeout_s
                )
            except asyncio.TimeoutError as exc:
                await stack.aclose()
                raise McpClientError(
                    "timeout",
                    f"initialize() exceeded {self._timeout_s}s",
                ) from exc
            except Exception as exc:  # noqa: BLE001
                await stack.aclose()
                raise McpClientError("handshake_failed", str(exc)) from exc

            self._stack = stack
            self._session = session
            self._opened_at = time.monotonic()
        except McpClientError:
            raise

    def _require_open(self) -> ClientSession:
        if self._closed or self._session is None:
            raise McpClientError("closed", "session is not open")
        return self._session

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return [{name, description, inputSchema}, ...] from MCP server.

        Raises McpClientError on timeout or transport failure.
        """
        sess = self._require_open()
        try:
            resp = await asyncio.wait_for(
                sess.list_tools(), timeout=self._timeout_s
            )
        except asyncio.TimeoutError as exc:
            raise McpClientError(
                "timeout", f"list_tools() exceeded {self._timeout_s}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise McpClientError("list_tools_failed", str(exc)) from exc

        out: list[dict[str, Any]] = []
        for t in getattr(resp, "tools", []) or []:
            schema = getattr(t, "inputSchema", None) or {}
            out.append(
                {
                    "name": getattr(t, "name", ""),
                    "description": getattr(t, "description", "") or "",
                    "inputSchema": schema,
                }
            )
        return out

    async def call_tool(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an MCP tool by name. Returns
        ``{tool, success, output, raw_content}`` so the caller does
        not have to handle the protocol-level content-parts shape.

        Raises McpClientError on transport failure / timeout. Tool-level
        ``isError=True`` results are returned (with success=False) so
        the handler layer can choose between propagating + auditing.
        """
        sess = self._require_open()
        try:
            resp = await asyncio.wait_for(
                sess.call_tool(name=name, arguments=arguments or {}),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError as exc:
            raise McpClientError(
                "timeout",
                f"call_tool({name}) exceeded {self._timeout_s}s",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise McpClientError("call_tool_failed", str(exc)) from exc

        # Mirror IWO2's serialiser: text parts are concatenated; non-text
        # parts get a placeholder so the caller sees something useful.
        parts = getattr(resp, "content", None) or []
        chunks: list[str] = []
        raw_content: list[dict[str, Any]] = []
        for part in parts:
            ptype = getattr(part, "type", "") or ""
            if ptype == "text":
                txt = getattr(part, "text", "") or ""
                chunks.append(txt)
                raw_content.append({"type": "text", "text": txt})
            elif ptype == "image":
                mime = getattr(part, "mimeType", "image") or "image"
                data = getattr(part, "data", "") or ""
                chunks.append(f"[Image: {mime}, {len(data)} bytes]")
                raw_content.append(
                    {"type": "image", "mimeType": mime, "size": len(data)}
                )
            elif ptype == "resource":
                uri = (
                    getattr(getattr(part, "resource", None), "uri", None)
                    or getattr(part, "uri", "unknown")
                    or "unknown"
                )
                chunks.append(f"[Resource: {uri}]")
                raw_content.append({"type": "resource", "uri": str(uri)})
            else:
                chunks.append(repr(part))
                raw_content.append(
                    {"type": ptype or "unknown", "repr": repr(part)}
                )

        is_error = bool(getattr(resp, "isError", False))
        return {
            "tool": name,
            "success": not is_error,
            "output": "\n".join(chunks) if chunks else "",
            "raw_content": raw_content,
        }

    async def close(self) -> None:
        """Tear down the stdio process + session. Idempotent."""
        if self._closed:
            return
        self._closed = True
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            try:
                await asyncio.wait_for(stack.aclose(), timeout=self._timeout_s)
            except asyncio.TimeoutError:
                log.warning(
                    "McpSession.close(%s) exceeded %.1fs; abandoning.",
                    self.server_name,
                    self._timeout_s,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "McpSession.close(%s) raised: %s",
                    self.server_name,
                    exc,
                )

    @property
    def is_open(self) -> bool:
        return not self._closed and self._session is not None

    @property
    def opened_at_monotonic(self) -> Optional[float]:
        return self._opened_at
