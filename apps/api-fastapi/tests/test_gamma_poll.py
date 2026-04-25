"""Loop 9 Phase 9.4 — Python gamma_poll helper integration.

Covers the FastAPI poll mirror (`adapter.gamma_poll.poll_gamma_handoff`):
  - completed response → handoff completed + audit
  - still-pending response → handoff stays submitted + polling audit
  - terminal failed response → handoff failed + failure audit
  - stale watchdog (forced) → handoff failed + watchdog audit
  - credential missing → credential_missing outcome
  - wrong handoff status → not_pollable

Uses httpx.MockTransport to stub Gamma responses; never reaches the
real API.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import asyncpg
import httpx
import pytest

from adapter.gamma_poll import poll_gamma_handoff


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_PPTX_TEMPLATE = "00000000-0000-4000-8000-000010000001"
KLEAR_WO = "00000000-0000-4000-8000-000060000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _transport(status: int, body) -> httpx.MockTransport:
    body_str = body if isinstance(body, str) else json.dumps(body)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            content=body_str.encode(),
            headers={"Content-Type": "application/json"},
        )

    return httpx.MockTransport(handler)


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])


async def _ensure_credential() -> str:
    conn = await _connect()
    try:
        catalog_id = await conn.fetchval(
            "SELECT id FROM adapter_catalog WHERE adapter_key = 'gamma'"
        )
        await conn.execute(
            """
            DELETE FROM adapter_credentials
             WHERE client_id = $1 AND adapter_catalog_id = $2
            """,
            KLEAR_CLIENT,
            catalog_id,
        )
        cred_id = await conn.fetchval(
            """
            INSERT INTO adapter_credentials
              (client_id, adapter_catalog_id, credential_ref, status,
               first_invocation_confirmed_at,
               first_invocation_confirmed_by_user_id)
            VALUES ($1, $2, 'credential_ref:env:GAMMA_POLL_TEST_KEY',
                    'active', now(), $3)
            RETURNING id::text
            """,
            KLEAR_CLIENT,
            catalog_id,
            KLEAR_OPERATOR,
        )
        return cred_id
    finally:
        await conn.close()


async def _insert_submitted_handoff(external_ref: str) -> str:
    """Insert a handoff in 'submitted' state for polling tests."""
    conn = await _connect()
    try:
        catalog_id = await conn.fetchval(
            "SELECT id FROM adapter_catalog WHERE adapter_key = 'gamma'"
        )
        pkg_id = await conn.fetchval(
            """
            INSERT INTO output_packages
              (client_id, work_order_id, output_kind, title,
               content_blocks, template_profile_id, created_by_user_id)
            VALUES ($1, $2, 'gamma_pptx', 'gamma_poll test pkg',
                    '{}'::jsonb, $3, $4)
            RETURNING id::text
            """,
            KLEAR_CLIENT,
            KLEAR_WO,
            KLEAR_PPTX_TEMPLATE,
            KLEAR_OPERATOR,
        )
        handoff_id = await conn.fetchval(
            """
            INSERT INTO output_handoffs
              (client_id, work_order_id, output_package_id,
               adapter_catalog_id, external_reference, status,
               last_poll_status, last_poll_at, poll_count)
            VALUES ($1, $2, $3, $4, $5,
                    'submitted'::output_handoff_status,
                    'pending', now(), 0)
            RETURNING id::text
            """,
            KLEAR_CLIENT,
            KLEAR_WO,
            pkg_id,
            catalog_id,
            external_ref,
        )
        return handoff_id
    finally:
        await conn.close()


async def _read_handoff(handoff_id: str) -> asyncpg.Record:
    conn = await _connect()
    try:
        return await conn.fetchrow(
            """
            SELECT status::text AS status,
                   last_poll_status, poll_count,
                   result_payload_ref
              FROM output_handoffs WHERE id = $1
            """,
            handoff_id,
        )
    finally:
        await conn.close()


def _parse_metadata(value: Any) -> dict:
    """asyncpg returns jsonb as a string by default — normalise to dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


async def _latest_audit(handoff_id: str) -> dict:
    conn = await _connect()
    try:
        row = await conn.fetchrow(
            """
            SELECT action, metadata
              FROM action_audit_log
             WHERE metadata->>'handoffId' = $1
                OR target_id = $1
             ORDER BY id DESC LIMIT 1
            """,
            handoff_id,
        )
        if row is None:
            return {"action": None, "metadata": {}}
        return {
            "action": row["action"],
            "metadata": _parse_metadata(row["metadata"]),
        }
    finally:
        await conn.close()


async def _cleanup_handoff(handoff_id: str) -> None:
    conn = await _connect()
    try:
        await conn.execute(
            """
            DELETE FROM external_execution_results
             WHERE output_handoff_id = $1
            """,
            handoff_id,
        )
        await conn.execute("DELETE FROM output_handoffs WHERE id = $1", handoff_id)
    finally:
        await conn.close()


@iwo3_db
def test_poll_completed_response_marks_handoff_completed() -> None:
    async def run() -> None:
        os.environ["GAMMA_POLL_TEST_KEY"] = "test-key"
        await _ensure_credential()
        handoff_id = await _insert_submitted_handoff("gen_poll_completed_test")
        try:
            conn = await _connect()
            try:
                out = await poll_gamma_handoff(
                    conn,
                    handoff_id=handoff_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    fetch_transport=_transport(
                        200,
                        {
                            "status": "completed",
                            "gammaUrl": "https://gamma.app/docs/x",
                            "exportUrls": [
                                "https://export.gamma.app/x.pptx"
                            ],
                        },
                    ),
                )
                assert out.kind == "completed"
                state = await _read_handoff(handoff_id)
                assert state["status"] == "completed"
                assert state["last_poll_status"] == "completed"
                audit = await _latest_audit(handoff_id)
                assert audit["action"] == "adapter_dispatch.completed"
            finally:
                await conn.close()
        finally:
            await _cleanup_handoff(handoff_id)
            del os.environ["GAMMA_POLL_TEST_KEY"]

    asyncio.run(run())


@iwo3_db
def test_poll_processing_response_stays_pending() -> None:
    async def run() -> None:
        os.environ["GAMMA_POLL_TEST_KEY"] = "test-key"
        await _ensure_credential()
        handoff_id = await _insert_submitted_handoff("gen_poll_pending_test")
        try:
            conn = await _connect()
            try:
                out = await poll_gamma_handoff(
                    conn,
                    handoff_id=handoff_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    fetch_transport=_transport(
                        200, {"status": "processing", "progress": 42}
                    ),
                )
                assert out.kind == "pending"
                state = await _read_handoff(handoff_id)
                assert state["status"] == "submitted"
                assert state["last_poll_status"] == "pending"
                assert state["poll_count"] == 1
                audit = await _latest_audit(handoff_id)
                assert audit["action"] == "adapter_dispatch.polling"
            finally:
                await conn.close()
        finally:
            await _cleanup_handoff(handoff_id)
            del os.environ["GAMMA_POLL_TEST_KEY"]

    asyncio.run(run())


@iwo3_db
def test_poll_failed_response_marks_handoff_failed() -> None:
    async def run() -> None:
        os.environ["GAMMA_POLL_TEST_KEY"] = "test-key"
        await _ensure_credential()
        handoff_id = await _insert_submitted_handoff("gen_poll_failed_test")
        try:
            conn = await _connect()
            try:
                out = await poll_gamma_handoff(
                    conn,
                    handoff_id=handoff_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    fetch_transport=_transport(
                        200,
                        {
                            "status": "failed",
                            "error": {"message": "generation died"},
                        },
                    ),
                )
                assert out.kind == "failed"
                state = await _read_handoff(handoff_id)
                assert state["status"] == "failed"
                assert state["last_poll_status"] == "failed"
                audit = await _latest_audit(handoff_id)
                assert audit["action"] == "adapter_dispatch.failed"
            finally:
                await conn.close()
        finally:
            await _cleanup_handoff(handoff_id)
            del os.environ["GAMMA_POLL_TEST_KEY"]

    asyncio.run(run())


@iwo3_db
def test_poll_force_stale_watchdog_fires() -> None:
    async def run() -> None:
        os.environ["GAMMA_POLL_TEST_KEY"] = "test-key"
        await _ensure_credential()
        handoff_id = await _insert_submitted_handoff(
            "gen_poll_watchdog_test"
        )
        try:
            conn = await _connect()
            try:
                out = await poll_gamma_handoff(
                    conn,
                    handoff_id=handoff_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    force_stale_watchdog=True,
                    fetch_transport=_transport(200, {"status": "processing"}),
                )
                assert out.kind == "watchdog_expired"
                state = await _read_handoff(handoff_id)
                assert state["status"] == "failed"
                assert state["last_poll_status"] == "watchdog_expired"
                audit = await _latest_audit(handoff_id)
                assert audit["action"] == (
                    "adapter_dispatch.watchdog_expired_stale_poll"
                )
                assert audit["metadata"]["forced"] is True
            finally:
                await conn.close()
        finally:
            await _cleanup_handoff(handoff_id)
            del os.environ["GAMMA_POLL_TEST_KEY"]

    asyncio.run(run())


@iwo3_db
def test_poll_credential_missing_env_var() -> None:
    async def run() -> None:
        os.environ.pop("GAMMA_POLL_TEST_KEY", None)
        await _ensure_credential()
        handoff_id = await _insert_submitted_handoff(
            "gen_poll_no_cred_test"
        )
        try:
            conn = await _connect()
            try:
                out = await poll_gamma_handoff(
                    conn,
                    handoff_id=handoff_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    fetch_transport=_transport(200, {"status": "completed"}),
                )
                assert out.kind == "credential_missing"
                state = await _read_handoff(handoff_id)
                # Handoff unchanged (still submitted).
                assert state["status"] == "submitted"
            finally:
                await conn.close()
        finally:
            await _cleanup_handoff(handoff_id)

    asyncio.run(run())


@iwo3_db
def test_poll_not_found_returns_typed_outcome() -> None:
    async def run() -> None:
        conn = await _connect()
        try:
            out = await poll_gamma_handoff(
                conn,
                handoff_id=str(uuid.uuid4()),
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert out.kind == "handoff_not_found"
        finally:
            await conn.close()

    asyncio.run(run())
