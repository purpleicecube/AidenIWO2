"""Loop 9 Phase 9.4 (scope §3.4) — Gamma handoff poll advance.

Python-side mirror of the TS ``pollHandoffStatus`` (lives in
`packages/contracts/adapter/registry.ts`). The FastAPI poll route
(`POST /output_handoffs/{id}/poll`) calls this.

Semantics (Darrel §Q3):
  - WO stays in `processing` during healthy rendering; poll state
    lives on the handoff.
  - Watchdog fires on stale poll (no fresh result within
    `adapter_actions.poll_timeout_seconds`) OR true terminal adapter
    failure.
  - Completed / failed results cascade via the caller, not here —
    this helper only advances handoff state + emits audit.

Pure response parsing reuses ``gamma_request_shape.parse_gamma_poll_response``
so the TS and Python codebases agree on Gamma's polymorphic polling
payload (verified byte-for-byte by ``gamma-request-shape-parity.test.ts``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union

import asyncpg
import httpx

from adapter.gamma_request_shape import parse_gamma_poll_response
from authz.audit_writer import write_audit_row
from llm.credentials import LlmCredentialError, resolve_credential


DEFAULT_POLL_TIMEOUT_SECONDS = 600  # 10 minutes; adapter_actions override

GAMMA_DEFAULT_BASE_URL = "https://public-api.gamma.app/v1.0"
GAMMA_FETCH_TIMEOUT_SECONDS = 30.0


PollResultKind = Literal[
    "completed",
    "pending",
    "failed",
    "watchdog_expired",
    "handoff_not_found",
    "handoff_not_pollable",
    "adapter_not_found",
    "credential_missing",
    "adapter_error",
]


@dataclass(frozen=True)
class PollOutcome:
    kind: PollResultKind
    handoff_id: str
    detail: Optional[str] = None
    poll_count: Optional[int] = None
    external_reference: Optional[str] = None
    result_payload_ref: Optional[str] = None
    elapsed_seconds: Optional[int] = None
    current_status: Optional[str] = None


async def _load_handoff_for_poll(
    conn: asyncpg.Connection, handoff_id: str, client_id: str
) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        """
        SELECT h.id::text                     AS id,
               h.status::text                 AS status,
               h.external_reference,
               h.adapter_catalog_id::text     AS adapter_catalog_id,
               h.last_poll_at,
               h.poll_count,
               h.output_package_id::text      AS output_package_id,
               cat.adapter_key,
               (
                 SELECT MAX(poll_timeout_seconds)
                   FROM adapter_actions
                  WHERE adapter_catalog_id = h.adapter_catalog_id
               )                              AS poll_timeout_seconds
          FROM output_handoffs h
     LEFT JOIN adapter_catalog cat ON cat.id = h.adapter_catalog_id
         WHERE h.id = $1 AND h.client_id = $2
        """,
        handoff_id,
        client_id,
    )


async def _load_credential_ref(
    conn: asyncpg.Connection, client_id: str, adapter_catalog_id: str
) -> Optional[str]:
    return await conn.fetchval(
        """
        SELECT credential_ref
          FROM adapter_credentials
         WHERE client_id = $1 AND adapter_catalog_id = $2
      ORDER BY created_at DESC
         LIMIT 1
        """,
        client_id,
        adapter_catalog_id,
    )


async def _update_handoff_status(
    conn: asyncpg.Connection,
    handoff_id: str,
    client_id: str,
    status: str,
    result_payload_ref: Optional[str],
) -> None:
    await conn.execute(
        """
        UPDATE output_handoffs
           SET status = $3::output_handoff_status,
               result_payload_ref = $4,
               updated_at = now()
         WHERE id = $1 AND client_id = $2
        """,
        handoff_id,
        client_id,
        status,
        result_payload_ref,
    )


async def _update_poll_state(
    conn: asyncpg.Connection,
    handoff_id: str,
    client_id: str,
    last_poll_status: str,
    increment: int,
) -> None:
    await conn.execute(
        """
        UPDATE output_handoffs
           SET last_poll_status = $3,
               last_poll_at = now(),
               poll_count = poll_count + $4,
               updated_at = now()
         WHERE id = $1 AND client_id = $2
        """,
        handoff_id,
        client_id,
        last_poll_status,
        increment,
    )


async def _emit_poll_audit(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    event: str,
    handoff_id: str,
    output_package_id: Optional[str],
    extra: dict,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event=event,
        target_type="adapter_dispatch",
        target_id=output_package_id or handoff_id,
        metadata={"handoffId": handoff_id, **extra},
    )


async def _fetch_gamma_result(
    api_key: str,
    external_reference: str,
    *,
    base_url: str = GAMMA_DEFAULT_BASE_URL,
    transport: Optional[httpx.BaseTransport] = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/generations/{external_reference}"
    with httpx.Client(
        timeout=GAMMA_FETCH_TIMEOUT_SECONDS, transport=transport
    ) as cli:
        resp = cli.get(url, headers={"X-API-KEY": api_key})
    resp.raise_for_status()
    return resp.json()


async def poll_gamma_handoff(
    conn: asyncpg.Connection,
    *,
    handoff_id: str,
    client_id: str,
    actor_user_id: Optional[str],
    now_override: Optional[datetime] = None,
    force_stale_watchdog: bool = False,
    fetch_transport: Optional[httpx.BaseTransport] = None,
    base_url: str = GAMMA_DEFAULT_BASE_URL,
) -> PollOutcome:
    """Poll a Gamma handoff and advance its lifecycle.

    Callers own the transaction. This helper writes to output_handoffs +
    action_audit_log using the tenant-scoped connection; RLS enforces
    cross-tenant isolation.
    """
    row = await _load_handoff_for_poll(conn, handoff_id, client_id)
    if row is None:
        return PollOutcome(kind="handoff_not_found", handoff_id=handoff_id)
    if row["status"] != "submitted":
        return PollOutcome(
            kind="handoff_not_pollable",
            handoff_id=handoff_id,
            current_status=row["status"],
        )
    if not row["adapter_catalog_id"] or not row["adapter_key"]:
        return PollOutcome(
            kind="adapter_not_found",
            handoff_id=handoff_id,
            detail="handoff has no adapter_catalog_id",
        )
    if row["adapter_key"] != "gamma":
        return PollOutcome(
            kind="adapter_not_found",
            handoff_id=handoff_id,
            detail=(
                f"Python poll mirror covers gamma only in Phase 9.4; "
                f"adapter={row['adapter_key']}"
            ),
        )
    if not row["external_reference"]:
        return PollOutcome(
            kind="adapter_not_found",
            handoff_id=handoff_id,
            detail="handoff missing external_reference",
        )

    poll_timeout = row["poll_timeout_seconds"] or DEFAULT_POLL_TIMEOUT_SECONDS
    now = now_override or datetime.now(timezone.utc)
    last_poll = row["last_poll_at"] or datetime.fromtimestamp(0, tz=timezone.utc)
    elapsed = int((now - last_poll).total_seconds())
    stale = force_stale_watchdog or elapsed > poll_timeout
    if stale:
        await _update_handoff_status(
            conn, handoff_id, client_id, "failed", None
        )
        await _update_poll_state(
            conn, handoff_id, client_id, "watchdog_expired", 0
        )
        await _emit_poll_audit(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="adapter_dispatch.watchdog_expired_stale_poll",
            handoff_id=handoff_id,
            output_package_id=row["output_package_id"],
            extra={
                "pollCount": row["poll_count"],
                "pollTimeoutSeconds": poll_timeout,
                "elapsedSeconds": elapsed,
                "forced": force_stale_watchdog,
            },
        )
        return PollOutcome(
            kind="watchdog_expired",
            handoff_id=handoff_id,
            detail=(
                f"no fresh poll within {poll_timeout}s (elapsed={elapsed}s)"
            ),
            elapsed_seconds=elapsed,
            poll_count=row["poll_count"],
        )

    credential_ref = await _load_credential_ref(
        conn, client_id, row["adapter_catalog_id"]
    )
    if not credential_ref:
        return PollOutcome(
            kind="credential_missing",
            handoff_id=handoff_id,
            detail="no adapter_credentials row for (client, gamma)",
        )
    try:
        api_key = resolve_credential(credential_ref)
    except LlmCredentialError as exc:
        return PollOutcome(
            kind="credential_missing",
            handoff_id=handoff_id,
            detail=f"credential_ref unresolved: {exc}",
        )

    try:
        raw = await _fetch_gamma_result(
            api_key,
            row["external_reference"],
            base_url=base_url,
            transport=fetch_transport,
        )
    except httpx.HTTPStatusError as exc:
        return PollOutcome(
            kind="adapter_error",
            handoff_id=handoff_id,
            detail=(
                f"gamma returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            ),
        )
    except httpx.HTTPError as exc:
        return PollOutcome(
            kind="adapter_error",
            handoff_id=handoff_id,
            detail=f"gamma network error: {exc}",
        )

    parsed = parse_gamma_poll_response(row["external_reference"], raw)
    next_count = row["poll_count"] + 1

    if parsed.status == "completed":
        payload_ref = (
            parsed.export_urls[0] if parsed.export_urls else parsed.gamma_url
        )
        await _update_handoff_status(
            conn, handoff_id, client_id, "completed", payload_ref
        )
        await _update_poll_state(
            conn, handoff_id, client_id, "completed", 1
        )
        await _emit_poll_audit(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="adapter_dispatch.completed",
            handoff_id=handoff_id,
            output_package_id=row["output_package_id"],
            extra={
                "externalReference": row["external_reference"],
                "pollCount": next_count,
            },
        )
        return PollOutcome(
            kind="completed",
            handoff_id=handoff_id,
            external_reference=row["external_reference"],
            result_payload_ref=payload_ref,
            poll_count=next_count,
        )

    if parsed.status == "failed":
        await _update_handoff_status(
            conn, handoff_id, client_id, "failed", None
        )
        await _update_poll_state(
            conn, handoff_id, client_id, "failed", 1
        )
        await _emit_poll_audit(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="adapter_dispatch.failed",
            handoff_id=handoff_id,
            output_package_id=row["output_package_id"],
            extra={
                "externalReference": row["external_reference"],
                "pollCount": next_count,
                "errorMessage": parsed.error_message,
                "stage": "poll",
            },
        )
        return PollOutcome(
            kind="failed",
            handoff_id=handoff_id,
            detail=parsed.error_message or "adapter returned failed",
            poll_count=next_count,
        )

    # Still pending (running / processing).
    await _update_poll_state(conn, handoff_id, client_id, "pending", 1)
    await _emit_poll_audit(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="adapter_dispatch.polling",
        handoff_id=handoff_id,
        output_package_id=row["output_package_id"],
        extra={
            "externalReference": row["external_reference"],
            "pollCount": next_count,
            "pollTimeoutSeconds": poll_timeout,
            "elapsedSeconds": elapsed,
        },
    )
    return PollOutcome(
        kind="pending",
        handoff_id=handoff_id,
        external_reference=row["external_reference"],
        poll_count=next_count,
        elapsed_seconds=elapsed,
    )
