"""Loop Xi — operator recovery tests.

Covers the three new /work_orders endpoints:

  POST /work_orders/{id}/reopen
  PUT  /work_orders/{id}
  POST /work_orders/{id}/redispatch

Each test seeds a fresh WO at the required starting status, exercises
the endpoint, and asserts the status / payload / RLS / audit row that
should result. Tests skip when IWO3_DATABASE_URL is unset (matches the
sibling test_work_orders_route.py pattern).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app

KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"
FFAI_OPERATOR = "00000000-0000-4000-8000-000002000003"
KLEAR_TEMPLATE_PPTX = "00000000-0000-4000-8000-000010000001"  # klear_pptx_primary

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


async def _seed_wo(status: str = "completed") -> str:
    """Insert a fresh WO at the requested status in Klear. Returns the id."""
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        new_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO work_orders
              (id, client_id, title, description, type, priority, status,
               submitted_by_user_id, correlation_id)
            VALUES ($1, $2, 'loop-xi test WO', 'original description',
                    'content_brief', 'medium', $3::work_order_status,
                    $4, 'loop-xi-test')
            """,
            new_id,
            KLEAR_CLIENT,
            status,
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
        await conn.execute(
            """
            DELETE FROM action_audit_log
             WHERE target_type = 'work_order' AND target_id = $1
            """,
            wo_id,
        )
        await conn.execute("DELETE FROM work_orders WHERE id = $1", wo_id)
    finally:
        await conn.close()


async def _audit_events_for(wo_id: str) -> list[str]:
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        rows = await conn.fetch(
            """
            SELECT action FROM action_audit_log
             WHERE target_type = 'work_order' AND target_id = $1
             ORDER BY created_at ASC
            """,
            wo_id,
        )
        return [r["action"] for r in rows]
    finally:
        await conn.close()


# ── POST /work_orders/{id}/reopen ──────────────────────────────────────


@iwo3_db
def test_reopen_completed_wo_happy_path() -> None:
    wo_id = asyncio.run(_seed_wo("completed"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/reopen",
                json={"reason": "template wrong; need Klear branding"},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["work_order_id"] == wo_id
        assert body["from"] == "completed"
        assert body["to"] == "processing"
        assert body["cycle_id"]  # transition_work_order writes a cycle row
        # Audit should include work_order.reopened (from transition helper).
        events = asyncio.run(_audit_events_for(wo_id))
        assert "work_order.reopened" in events
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_reopen_requires_non_empty_reason() -> None:
    wo_id = asyncio.run(_seed_wo("completed"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/reopen",
                json={"reason": ""},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 422
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_reopen_rejected_from_active_status() -> None:
    """Cannot reopen a WO that is already pending/processing — only
    terminal states qualify per IWO2 parity."""
    wo_id = asyncio.run(_seed_wo("pending"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/reopen",
                json={"reason": "bad client request"},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "not_reopenable"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_reopen_viewer_role_denied() -> None:
    wo_id = asyncio.run(_seed_wo("completed"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/reopen",
                json={"reason": "viewer attempt"},
                headers={
                    "X-IWO3-User": KLEAR_VIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        # require_permission_dep gates on work_order:update — viewer
        # has no such grant, so the dep raises 403 before the handler.
        assert r.status_code == 403
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_reopen_cross_tenant_404() -> None:
    """A Klear-owned WO is invisible to FFAI; reopen attempt 404s.
    RLS scopes the SELECT in the handler so the row isn't visible."""
    wo_id = asyncio.run(_seed_wo("completed"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/reopen",
                json={"reason": "tenant boundary probe"},
                headers={
                    "X-IWO3-User": FFAI_OPERATOR,
                    "X-IWO3-Client": FFAI_CLIENT,
                },
            )
        assert r.status_code == 404
    finally:
        asyncio.run(_drop_wo(wo_id))


# ── PUT /work_orders/{id} ──────────────────────────────────────────────


@iwo3_db
def test_edit_partial_update_happy_path() -> None:
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            r = client.put(
                f"/work_orders/{wo_id}",
                json={
                    "title": "edited title",
                    "description": "revised description with Klear template intent",
                    "priority": "high",
                },
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["title"] == "edited title"
        assert body["description"] == "revised description with Klear template intent"
        assert body["priority"] == "high"
        # type unchanged because we didn't supply it.
        assert body["type"] == "content_brief"
        events = asyncio.run(_audit_events_for(wo_id))
        assert "work_order.edited" in events
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_edit_with_valid_template_profile_id() -> None:
    """The Loop Xi explicit-template upgrade — operator can attach a
    template_profile_id and it lands in requested_outputs."""
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            r = client.put(
                f"/work_orders/{wo_id}",
                json={"template_profile_id": KLEAR_TEMPLATE_PPTX},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        # Verify requested_outputs was set on the WO.
        url = os.environ["IWO3_DATABASE_URL"]

        async def _check() -> dict:
            conn = await asyncpg.connect(dsn=url)
            try:
                row = await conn.fetchrow(
                    "SELECT requested_outputs FROM work_orders WHERE id = $1",
                    wo_id,
                )
                return dict(row) if row else {}
            finally:
                await conn.close()

        ro_row = asyncio.run(_check())
        ro = ro_row["requested_outputs"]
        # asyncpg returns jsonb as a dict via codec; fall back to str-decode.
        if isinstance(ro, str):
            import json
            ro = json.loads(ro)
        assert ro["template_profile_id"] == KLEAR_TEMPLATE_PPTX
        assert ro["output_kind"] == "pptx"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_edit_invalid_priority_422() -> None:
    wo_id = asyncio.run(_seed_wo("pending"))
    try:
        with TestClient(app) as client:
            r = client.put(
                f"/work_orders/{wo_id}",
                json={"priority": "ultra"},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "invalid_priority"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_edit_blocked_status_rejected() -> None:
    """Edits not allowed on terminal/non-active statuses — operator
    must reopen first."""
    wo_id = asyncio.run(_seed_wo("completed"))
    try:
        with TestClient(app) as client:
            r = client.put(
                f"/work_orders/{wo_id}",
                json={"title": "cannot edit terminal"},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "not_editable"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_edit_unknown_template_profile_422() -> None:
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            r = client.put(
                f"/work_orders/{wo_id}",
                json={
                    "template_profile_id": "00000000-0000-4000-8000-0000ffff0fff"
                },
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "template_profile_not_found"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_edit_no_op_returns_current_row() -> None:
    """Empty payload — no fields supplied — should return the current
    row without writing an audit event."""
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            r = client.put(
                f"/work_orders/{wo_id}",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200
        events = asyncio.run(_audit_events_for(wo_id))
        assert "work_order.edited" not in events
    finally:
        asyncio.run(_drop_wo(wo_id))


# ── POST /work_orders/{id}/redispatch ──────────────────────────────────


@iwo3_db
def test_redispatch_rejected_from_terminal_status() -> None:
    """Cannot redispatch a completed WO — must reopen first."""
    wo_id = asyncio.run(_seed_wo("completed"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/redispatch",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "not_redispatchable"
        # Audit row should NOT be written when validation rejects.
        events = asyncio.run(_audit_events_for(wo_id))
        assert "work_order.redispatched" not in events
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_redispatch_writes_audit_event_upfront() -> None:
    """Even if dispatch returns clarification or fails to find a config,
    the redispatch audit row should land BEFORE delegation. We can't
    cleanly mock Aiden in this test harness so we just assert the audit
    row appears regardless of dispatch outcome."""
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            client.post(
                f"/work_orders/{wo_id}/redispatch",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
            # We don't assert the response code — the dispatch may
            # succeed (live LLM) or 409 with no_aiden_config etc. The
            # invariant we care about is that the audit row landed.
        events = asyncio.run(_audit_events_for(wo_id))
        assert "work_order.redispatched" in events
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_redispatch_viewer_role_denied() -> None:
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/redispatch",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_VIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 403
    finally:
        asyncio.run(_drop_wo(wo_id))
