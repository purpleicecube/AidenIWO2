"""Loop 7 Phase 7.2 — /work_orders route tests.

Loop 9 Phase 9.0 extension: direct coverage for
``GET /work_orders/metrics`` and ``POST /work_orders`` — both back
user-facing shell surfaces (Dashboard metric cards + Submit Order form)
and previously lived behind only view-import smoke tests in
``apps/console-streamlit/tests``.
"""

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
def test_metrics_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/work_orders/metrics")
    assert r.status_code == 401


@iwo3_db
def test_metrics_klear_tenant_scoped() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/work_orders/metrics",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    # RLS filters to Klear; FFAI WOs are never counted.
    assert body["total"] >= 1
    assert isinstance(body["by_status"], dict)
    assert body["total"] == sum(body["by_status"].values())
    assert body["reopened_count"] >= 0


@iwo3_db
def test_metrics_viewer_can_read() -> None:
    # Viewer has `work_order:read`, so /metrics is allowed.
    with TestClient(app) as client:
        r = client.get(
            "/work_orders/metrics",
            headers={
                "X-IWO3-User": KLEAR_VIEWER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    assert "total" in r.json()


@iwo3_db
def test_metrics_counts_grow_after_create() -> None:
    # Independent read → create → read: total must strictly increase
    # by 1 and pending must also tick by 1.
    with TestClient(app) as client:
        before = client.get(
            "/work_orders/metrics",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        ).json()
        post = client.post(
            "/work_orders",
            json={
                "title": "phase-9.0 metrics delta test",
                "type": "content_brief",
                "priority": "medium",
                "correlation_id": "loop9-phase0-metrics",
            },
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
        assert post.status_code == 200, post.text
        new_id = post.json()["id"]
        try:
            after = client.get(
                "/work_orders/metrics",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            ).json()
            assert after["total"] == before["total"] + 1
            assert (
                after["by_status"].get("pending", 0)
                == before["by_status"].get("pending", 0) + 1
            )
        finally:
            import asyncio

            asyncio.run(_drop_wo(new_id))


@iwo3_db
def test_create_wo_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={"title": "no auth", "type": "content_brief"},
        )
    assert r.status_code == 401


@iwo3_db
def test_create_wo_operator_creates_pending() -> None:
    import asyncio

    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={
                "title": "phase-9.0 create-test WO",
                "description": "Created via POST /work_orders route test.",
                "type": "content_brief",
                "priority": "high",
                "correlation_id": "loop9-phase0-create",
            },
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["client_id"] == KLEAR_CLIENT
    assert body["priority"] == "high"
    assert body["correlation_id"] == "loop9-phase0-create"
    assert body["submitted_by_user_id"] == KLEAR_OPERATOR
    asyncio.run(_drop_wo(body["id"]))


@iwo3_db
def test_create_wo_viewer_forbidden() -> None:
    # Viewer lacks `work_order:create` — must 403.
    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={"title": "viewer create denied", "type": "content_brief"},
            headers={
                "X-IWO3-User": KLEAR_VIEWER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "permission_denied"


@iwo3_db
def test_create_wo_invalid_priority_returns_422() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={
                "title": "bad priority",
                "type": "content_brief",
                "priority": "urgent",
            },
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "invalid_priority"
    assert r.json()["detail"]["priority"] == "urgent"


@iwo3_db
def test_create_wo_tenant_scoped() -> None:
    # Actor is Klear → created WO must be in Klear. Independent sanity
    # check that `client_id` comes from the actor context, not the body.
    import asyncio

    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={"title": "tenant-scope test", "type": "content_brief"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_id"] == KLEAR_CLIENT
    assert body["client_id"] != FFAI_CLIENT
    asyncio.run(_drop_wo(body["id"]))


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
