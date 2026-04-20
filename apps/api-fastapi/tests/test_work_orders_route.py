"""Loop 7 Phase 7.2 — /work_orders route tests."""

from __future__ import annotations

import os
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app

KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"
KLEAR_AGENT = "00000000-0000-4000-8000-000001000006"

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


async def _new_test_wo() -> str:
    """Inserts a fresh pending WO in Klear for the next test. Returns the id."""
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        new_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO work_orders
              (id, client_id, title, type, priority, status,
               submitted_by_user_id, correlation_id)
            VALUES ($1, $2, 'phase-7.2 route test WO', 'content_brief',
                    'medium', 'pending', $3, 'loop7-phase2-test')
            """,
            new_id,
            KLEAR_CLIENT,
            KLEAR_OPERATOR,
        )
        return new_id
    finally:
        await conn.close()


async def _drop_wo(wo_id: str) -> None:
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        await conn.execute(
            "DELETE FROM execution_cycles WHERE work_order_id = $1",
            wo_id,
        )
        await conn.execute("DELETE FROM work_orders WHERE id = $1", wo_id)
    finally:
        await conn.close()


@iwo3_db
def test_list_work_orders_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/work_orders")
    assert r.status_code == 401


@iwo3_db
def test_list_work_orders_klear_sees_only_klear_rows() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/work_orders",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200
    wos = r.json()["work_orders"]
    # Klear seed has at least 1 WO; RLS filters out FFAI rows.
    assert len(wos) >= 1
    for wo in wos:
        assert wo["client_id"] == KLEAR_CLIENT


@iwo3_db
def test_viewer_can_list_wos_but_cannot_transition() -> None:
    import asyncio

    wo_id = asyncio.run(_new_test_wo())
    try:
        with TestClient(app) as client:
            # Viewer can read
            r_list = client.get(
                "/work_orders",
                headers={
                    "X-IWO3-User": KLEAR_VIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
            assert r_list.status_code == 200
            # Viewer cannot transition (lacks work_order:submit)
            r_tx = client.post(
                f"/work_orders/{wo_id}/transition",
                json={"to": "processing"},
                headers={
                    "X-IWO3-User": KLEAR_VIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
            assert r_tx.status_code == 403
            assert r_tx.json()["detail"]["error"] == "permission_denied"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_operator_transitions_pending_to_processing() -> None:
    import asyncio

    wo_id = asyncio.run(_new_test_wo())
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/transition",
                json={"to": "processing", "reason": "smoke test"},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["from"] == "pending"
        assert body["to"] == "processing"
        assert body["event"] == "work_order.transitioned"
        assert body["cycle_id"] is None
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_illegal_transition_returns_409() -> None:
    import asyncio

    wo_id = asyncio.run(_new_test_wo())
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/transition",
                json={"to": "completed"},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "illegal_transition"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_watchdog_expire_requires_processing() -> None:
    import asyncio

    wo_id = asyncio.run(_new_test_wo())
    try:
        with TestClient(app) as client:
            # WO is pending — watchdog rejects
            r = client.post(
                f"/work_orders/{wo_id}/watchdog_expire",
                json={"reason": "timer"},
                headers={
                    "X-IWO3-User": KLEAR_AGENT,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
            assert r.status_code == 409
            # Move to processing, then watchdog
            r2 = client.post(
                f"/work_orders/{wo_id}/transition",
                json={"to": "processing"},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
            assert r2.status_code == 200
            r3 = client.post(
                f"/work_orders/{wo_id}/watchdog_expire",
                json={"reason": "no heartbeat 10min"},
                headers={
                    "X-IWO3-User": KLEAR_AGENT,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
            assert r3.status_code == 200, r3.text
            body = r3.json()
            assert body["to"] == "blocked"
            assert body["event"] == "work_order.watchdog_expired"
            assert body["cycle_id"] is not None
    finally:
        asyncio.run(_drop_wo(wo_id))
