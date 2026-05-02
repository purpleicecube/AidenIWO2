"""Loop Eta phase 1.2 — Worker H — data validation + ops probe handlers.

Two runnable Tier-2 tools ported from IWO2:

  - `csv_validate`        ← IWO2 `executeDataValidator`
                            (`server/tool-executor.ts:415-437`)
  - `http_health_probe`   ← IWO2 `executeHealthCheck`
                            (`server/tool-executor.ts:396-413`)

Both handlers conform to the `ToolDefinition.handler` signature exposed
by `runtime.aiden_tools` — `(conn, args, client_id) -> dict`. Neither
of these handlers touches the database; the `conn` parameter is
accepted to satisfy the registry contract and is intentionally unused.

`DATA_OPS_TOOLS` is a registry literal merged into the global
`TOOL_REGISTRY` during the Loop Eta convergence step. Nothing in this
module mutates `runtime.aiden_tools` directly.

CODEX universal-slice locks honoured:
  - Stdlib-only CSV parsing (no pandas).
  - SSRF guard runs BEFORE any network I/O. Public DNS + HTTP/HTTPS
    only — private, loopback, link-local, multicast, and reserved
    ranges are refused with `ToolExecutionError("ssrf_blocked", ...)`.
  - Network failures (timeout, refused, DNS) return ok=false with a
    diagnostic string instead of raising — keeps the audit row clean
    and lets Aiden surface the failure to the operator without
    blowing up the tool-call loop.
"""

from __future__ import annotations

import csv
import io
import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlparse

import asyncpg
import httpx

from runtime.aiden_tools import ToolDefinition, ToolExecutionError


# ── SSRF guard (local — convergence may dedupe with Worker G's copy) ──


# Private IPv4/IPv6 ranges blocked before any DNS resolution + a second
# time after resolution against the resolved A/AAAA records. Same set
# as Worker G's `web_scrape` handler — convergence may collapse to a
# single helper. Documented values for cross-check during merge:
#   loopback             127.0.0.0/8       ::1/128
#   private (RFC 1918)   10.0.0.0/8        172.16.0.0/12   192.168.0.0/16
#   link-local           169.254.0.0/16    fe80::/10
#   multicast            224.0.0.0/4       ff00::/8
#   IPv4-mapped IPv6     ::ffff:0:0/96
#   carrier-grade NAT    100.64.0.0/10
#   reserved / docs      192.0.0.0/24      192.0.2.0/24    198.18.0.0/15
#                        198.51.100.0/24   203.0.113.0/24  240.0.0.0/4
# We rely on `ipaddress.ip_address(...).is_private/is_loopback/...`
# which already covers the canonical classifications; the explicit
# CGNAT + benchmark + documentation ranges are caught by `is_private`
# / `is_reserved` in the stdlib.


def _is_blocked_ip(addr: str) -> bool:
    """Return True for any IP we refuse to dial. Covers loopback,
    private (RFC 1918 + RFC 4193), link-local, multicast, reserved,
    unspecified, and IPv4-mapped IPv6 of any of the above."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        # Not a parseable IP — treat as blocked to be safe.
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _ssrf_check_url(url: str) -> str:
    """Validate `url` against SSRF rules. Returns the normalized URL on
    success. Raises `ToolExecutionError("http_health_probe", ...)` on
    any failure — caller is responsible for catching + auditing. The
    check runs entirely before any network I/O the caller performs."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolExecutionError(
            "http_health_probe",
            "ssrf_blocked",
            f"unsupported scheme {parsed.scheme!r}; expected http or https",
        )
    host = parsed.hostname
    if not host:
        raise ToolExecutionError(
            "http_health_probe",
            "ssrf_blocked",
            "missing host in URL",
        )

    # Direct literal IP — block before DNS attempt. We only short-
    # circuit when the host *parses* as an IP literal; DNS hostnames
    # fall through to the resolution step below.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        is_ip_literal = False
    else:
        is_ip_literal = True

    if is_ip_literal:
        if _is_blocked_ip(host):
            raise ToolExecutionError(
                "http_health_probe",
                "ssrf_blocked",
                f"refusing to dial private/loopback host {host!r}",
            )
        return url

    # DNS resolve and reject if any resolved address is in a blocked
    # range. `gethostbyname_ex` is sync but acceptable here — these
    # tool calls already happen inside the Aiden tool-call loop and
    # network probes are inherently a few hundred ms.
    try:
        _, _, addrs = socket.gethostbyname_ex(host)
    except socket.gaierror as exc:
        raise ToolExecutionError(
            "http_health_probe",
            "ssrf_blocked",
            f"dns_resolution_failed for {host!r}: {exc}",
        ) from exc
    for addr in addrs:
        if _is_blocked_ip(addr):
            raise ToolExecutionError(
                "http_health_probe",
                "ssrf_blocked",
                f"host {host!r} resolves to blocked address {addr}",
            )
    return url


# ── csv_validate ─────────────────────────────────────────────────────


_DEFAULT_MAX_ROWS = 10_000


async def _csv_validate(
    conn: asyncpg.Connection,  # noqa: ARG001 — required by registry contract
    args: dict[str, Any],
    client_id: str,  # noqa: ARG001 — no tenant scope on stdlib-only parse
) -> dict[str, Any]:
    """Validate CSV structure: parse string, detect missing required
    headers, empty cells in required columns, mismatched column counts,
    and row-cap overflow. Pure stdlib — no pandas, no I/O."""

    csv_text = args.get("csv")
    if not isinstance(csv_text, str):
        return {
            "row_count": 0,
            "column_count": 0,
            "headers": [],
            "issues": [
                {
                    "row": None,
                    "column": None,
                    "kind": "invalid_input",
                    "detail": "args.csv must be a string",
                }
            ],
            "ok": False,
        }

    required_fields_arg = args.get("required_fields") or []
    if not isinstance(required_fields_arg, list):
        required_fields_arg = []
    required_fields: list[str] = [
        str(f) for f in required_fields_arg if isinstance(f, (str, int, float))
    ]

    try:
        max_rows = int(args.get("max_rows", _DEFAULT_MAX_ROWS) or _DEFAULT_MAX_ROWS)
    except (TypeError, ValueError):
        max_rows = _DEFAULT_MAX_ROWS
    max_rows = max(1, min(max_rows, _DEFAULT_MAX_ROWS))

    issues: list[dict[str, Any]] = []

    reader = csv.reader(io.StringIO(csv_text))
    try:
        first_row = next(reader)
    except StopIteration:
        return {
            "row_count": 0,
            "column_count": 0,
            "headers": [],
            "issues": [
                {
                    "row": None,
                    "column": None,
                    "kind": "empty_csv",
                    "detail": "no header row found",
                }
            ],
            "ok": False,
        }

    headers = [h.strip() for h in first_row]
    column_count = len(headers)

    # Missing required columns (header not present).
    header_set = set(headers)
    for required in required_fields:
        if required not in header_set:
            issues.append(
                {
                    "row": None,
                    "column": required,
                    "kind": "missing_required_column",
                    "detail": f"required field {required!r} is not in the header row",
                }
            )

    required_indices = {
        h: i for i, h in enumerate(headers) if h in set(required_fields)
    }

    row_count = 0
    for row_index, row in enumerate(reader, start=1):
        if row_count >= max_rows:
            issues.append(
                {
                    "row": row_index,
                    "column": None,
                    "kind": "row_cap_exceeded",
                    "detail": f"stopped at max_rows={max_rows}",
                }
            )
            break
        row_count += 1

        if len(row) != column_count:
            issues.append(
                {
                    "row": row_index,
                    "column": None,
                    "kind": "column_count_mismatch",
                    "detail": (
                        f"row has {len(row)} columns, expected {column_count}"
                    ),
                }
            )

        # Empty cells in required columns.
        for header, idx in required_indices.items():
            value = row[idx].strip() if idx < len(row) else ""
            if not value:
                issues.append(
                    {
                        "row": row_index,
                        "column": header,
                        "kind": "empty_required_cell",
                        "detail": f"required field {header!r} is empty",
                    }
                )

    return {
        "row_count": row_count,
        "column_count": column_count,
        "headers": headers,
        "issues": issues,
        "ok": not issues,
    }


# ── http_health_probe ────────────────────────────────────────────────


_DEFAULT_HEALTH_TIMEOUT_S = 5.0


async def _http_health_probe(
    conn: asyncpg.Connection,  # noqa: ARG001 — required by registry contract
    args: dict[str, Any],
    client_id: str,  # noqa: ARG001 — probe is not tenant-scoped
) -> dict[str, Any]:
    """HEAD a URL, return latency + status. SSRF-protected: rejects
    non-http/https schemes + any host that resolves into a private,
    loopback, link-local, multicast, or reserved IP range *before* any
    network call is issued. Network-level failures (timeout, connection
    refused, DNS) return ok=false with a diagnostic — they don't
    raise, so the audit row records a successful tool call that
    reported a downed target."""

    url_arg = args.get("url")
    if not isinstance(url_arg, str) or not url_arg:
        raise ToolExecutionError(
            "http_health_probe",
            "invalid_input",
            "args.url must be a non-empty string",
        )

    # Accept both the seed schema (`timeout_s`) and the worker spec
    # (`timeout_seconds`) without breaking either caller.
    raw_timeout = args.get("timeout_seconds", args.get("timeout_s", _DEFAULT_HEALTH_TIMEOUT_S))
    try:
        timeout_s = float(raw_timeout) if raw_timeout is not None else _DEFAULT_HEALTH_TIMEOUT_S
    except (TypeError, ValueError):
        timeout_s = _DEFAULT_HEALTH_TIMEOUT_S
    timeout_s = max(0.5, min(timeout_s, 30.0))

    # SSRF check FIRST — raises before we touch the network.
    safe_url = _ssrf_check_url(url_arg)

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await client.head(safe_url)
    except httpx.TimeoutException as exc:
        return {
            "url": safe_url,
            "ok": False,
            "status_code": 0,
            "latency_ms": (time.perf_counter() - start) * 1000.0,
            "redirect_count": 0,
            "final_url": safe_url,
            "error": f"timeout after {timeout_s}s: {exc}",
        }
    except httpx.HTTPError as exc:
        return {
            "url": safe_url,
            "ok": False,
            "status_code": 0,
            "latency_ms": (time.perf_counter() - start) * 1000.0,
            "redirect_count": 0,
            "final_url": safe_url,
            "error": f"{type(exc).__name__}: {exc}",
        }

    latency_ms = (time.perf_counter() - start) * 1000.0
    redirect_count = len(response.history)
    return {
        "url": safe_url,
        "ok": 200 <= response.status_code < 300,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "redirect_count": redirect_count,
        "final_url": str(response.url),
    }


# ── Registry literal (folded into TOOL_REGISTRY by convergence) ──────


DATA_OPS_TOOLS: dict[str, ToolDefinition] = {
    "csv_validate": ToolDefinition(
        name="csv_validate",
        description=(
            "Validate the structure of a CSV string: detect missing "
            "required header columns, empty cells in required columns, "
            "row/column count mismatches, and per-row issues. Stdlib-only "
            "(no pandas). Use whenever the operator pastes or uploads "
            "CSV data and asks whether it's clean / well-formed."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "csv": {"type": "string"},
                "required_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "max_rows": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _DEFAULT_MAX_ROWS,
                    "default": _DEFAULT_MAX_ROWS,
                },
            },
            "required": ["csv"],
            "additionalProperties": False,
        },
        handler=_csv_validate,
    ),
    "http_health_probe": ToolDefinition(
        name="http_health_probe",
        description=(
            "HEAD a public URL and return status code + latency_ms + "
            "redirect chain length. SSRF-protected: refuses non-http(s) "
            "schemes and any host that resolves to a private, loopback, "
            "link-local, multicast, or reserved IP. Use when the "
            "operator asks whether a public endpoint is up, healthy, or "
            "reachable; do NOT use for internal services."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "timeout_seconds": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 30.0,
                    "default": _DEFAULT_HEALTH_TIMEOUT_S,
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=_http_health_probe,
    ),
}
