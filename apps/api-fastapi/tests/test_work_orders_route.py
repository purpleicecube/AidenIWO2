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


# ─── Beta-2 phase 0.1 — requested_outputs on POST /work_orders ──────────

KLEAR_PPTX_TID = "00000000-0000-4000-8000-000010000001"  # klear_pptx_primary
FFAI_TID = "00000000-0000-4000-8000-000020000002"        # cross-tenant


@iwo3_db
def test_create_wo_with_requested_outputs_persists() -> None:
    """Happy path: operator supplies output_kind + template_profile_id;
    server validates, persists requested_outputs jsonb, and emits the
    work_order.requested_outputs_set audit row."""
    import asyncio
    import json as _json

    async def _fetch_audit_and_wo(wo_id: str):
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await asyncpg.connect(dsn=url)
        try:
            wo_row = await conn.fetchrow(
                "SELECT requested_outputs::text AS ro FROM work_orders WHERE id = $1::uuid",
                wo_id,
            )
            audit_row = await conn.fetchrow(
                """
                SELECT action, target_id,
                       metadata::text AS metadata
                  FROM action_audit_log
                 WHERE target_id = $1
                   AND action = 'work_order.requested_outputs_set'
                 ORDER BY created_at DESC LIMIT 1
                """,
                wo_id,
            )
            return wo_row, audit_row
        finally:
            await conn.close()

    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={
                "title": "phase-0.1 requested_outputs persist test",
                "type": "content_brief",
                "priority": "medium",
                "correlation_id": "phase-0.1-test-persist",
                "output_kind": "pptx",
                "template_profile_id": KLEAR_PPTX_TID,
            },
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    wo_id = r.json()["id"]
    try:
        wo_row, audit_row = asyncio.run(_fetch_audit_and_wo(wo_id))
        assert wo_row is not None
        ro = _json.loads(wo_row["ro"])
        assert ro["output_kind"] == "pptx"
        assert ro["template_profile_id"] == KLEAR_PPTX_TID
        assert audit_row is not None
        meta = _json.loads(audit_row["metadata"])
        assert meta["output_kind"] == "pptx"
        assert meta["template_profile_id"] == KLEAR_PPTX_TID
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_create_wo_unknown_template_profile_id_returns_422() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={
                "title": "phase-0.1 unknown tid",
                "type": "content_brief",
                "priority": "medium",
                "template_profile_id": "00000000-0000-4000-8000-deadbeefdead",
            },
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "template_profile_not_found"


@iwo3_db
def test_create_wo_output_kind_template_mismatch_returns_422() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={
                "title": "phase-0.1 mismatch",
                "type": "content_brief",
                "priority": "medium",
                "output_kind": "pdf",
                "template_profile_id": KLEAR_PPTX_TID,
            },
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "output_kind_template_mismatch"
    assert detail["output_kind"] == "pdf"
    assert detail["template_profile_output_kind"] == "pptx"


@iwo3_db
def test_create_wo_output_kind_alone_unknown_returns_422() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={
                "title": "phase-0.1 unknown kind",
                "type": "content_brief",
                "priority": "medium",
                "output_kind": "nonexistent_kind",
            },
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "no_published_template_for_output_kind"
    assert detail["output_kind"] == "nonexistent_kind"


@iwo3_db
def test_create_wo_cross_tenant_template_returns_not_found() -> None:
    """Klear context, FFAI's template_profile_id. RLS scopes the lookup
    to Klear, so the row is invisible — server returns 422
    template_profile_not_found (not 403; we don't leak existence)."""
    with TestClient(app) as client:
        r = client.post(
            "/work_orders",
            json={
                "title": "phase-0.1 cross-tenant",
                "type": "content_brief",
                "priority": "medium",
                "template_profile_id": FFAI_TID,
            },
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "template_profile_not_found"
    assert detail["template_profile_id"] == FFAI_TID
