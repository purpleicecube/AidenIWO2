"""Aiden Evaluator Parity Loop tests (2026-05-11).

Two new endpoints under test:

  GET  /work_orders/{id}/evaluator_summary
  POST /work_orders/{id}/accept

Pattern mirrors test_work_orders_xi_route.py — seed a fresh WO at the
required starting status, exercise the endpoint, assert the
status/payload/RLS/audit row. Tests skip when IWO3_DATABASE_URL is
unset.
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

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


async def _seed_wo(status: str = "awaiting_operator") -> str:
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        new_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO work_orders
              (id, client_id, title, description, type, priority, status,
               submitted_by_user_id, correlation_id)
            VALUES ($1, $2, 'loop-aep test WO', 'AEP test seed',
                    'content_brief', 'medium', $3::work_order_status,
                    $4, 'loop-aep-test')
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
            "DELETE FROM execution_cycles WHERE work_order_id = $1", wo_id
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


async def _seed_audit_review_event(wo_id: str, agent_role: str) -> int:
    """Insert a fake llm.invoked audit row with review metadata so the
    evaluator_summary's audit-derive path has something to find."""
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        # action_audit_log.id is bigint (identity); let the DB
        # auto-generate it. Return the generated id.
        row = await conn.fetchrow(
            """
            INSERT INTO action_audit_log
              (client_id, actor_user_id, action, target_type, target_id,
               metadata, created_at)
            VALUES ($1::uuid, $2::uuid, 'llm.invoked', 'work_order',
                    $3, $4::jsonb, now())
            RETURNING id
            """,
            KLEAR_CLIENT,
            KLEAR_OPERATOR,
            wo_id,
            (
                f'{{"agentRole":"{agent_role}",'
                '"decisionKind":"revise",'
                '"score":0.62,'
                '"issues":["unclear conclusion","missing citation"],'
                '"summary":"Revise: tighten the conclusion and cite source."}'
            ),
        )
        return int(row["id"])
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


# ── GET /work_orders/{id}/evaluator_summary ────────────────────────────


@iwo3_db
def test_evaluator_summary_basic_shape() -> None:
    """Happy path: WO with no audit → aiden_review null, done_contract
    populated, candidate_review null, checklist empty or near-empty."""
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            r = client.get(
                f"/work_orders/{wo_id}/evaluator_summary",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["work_order"]["id"] == wo_id
        assert body["work_order"]["status"] == "processing"
        assert body["aiden_review"] is None
        assert body["done_contract"]["status"] == "processing"
        assert body["done_contract"]["required_action"] is not None
        assert body["candidate_review"] is None
        assert body["reopen_metadata"] is None
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_evaluator_summary_audit_derived_review() -> None:
    """When an llm.invoked event with pm_review-like agentRole exists,
    aiden_review should be derived from its metadata."""
    wo_id = asyncio.run(_seed_wo("awaiting_operator"))
    try:
        asyncio.run(_seed_audit_review_event(wo_id, "pm_review"))
        with TestClient(app) as client:
            r = client.get(
                f"/work_orders/{wo_id}/evaluator_summary",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        ar = body["aiden_review"]
        assert ar is not None
        assert ar["recommendation"] == "revise"
        assert ar["score"] == 0.62
        assert ar["approved"] is False
        assert ar["flagged"] is True
        assert "unclear conclusion" in ar["issues"]
        assert ar["agent_role"] == "pm_review"
        assert ar["source"] == "audit_derived"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_evaluator_summary_audit_derived_alternative_role_tag() -> None:
    """The role-tag allowlist includes aiden_quality + others, not just
    pm_review. Lock that vocabulary so a future contributor doesn't
    silently narrow it."""
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        asyncio.run(_seed_audit_review_event(wo_id, "aiden_quality"))
        with TestClient(app) as client:
            r = client.get(
                f"/work_orders/{wo_id}/evaluator_summary",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        assert r.json()["aiden_review"] is not None
        assert r.json()["aiden_review"]["agent_role"] == "aiden_quality"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_evaluator_summary_unknown_role_does_not_match() -> None:
    """An llm.invoked event with an unrelated agentRole (e.g., a
    sub-agent role like 'mark' or 'tom') must NOT be misclassified
    as an Aiden review."""
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        asyncio.run(_seed_audit_review_event(wo_id, "tom_tier_2"))
        with TestClient(app) as client:
            r = client.get(
                f"/work_orders/{wo_id}/evaluator_summary",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        assert r.json()["aiden_review"] is None
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_evaluator_summary_cross_tenant_404() -> None:
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            r = client.get(
                f"/work_orders/{wo_id}/evaluator_summary",
                headers={
                    "X-IWO3-User": FFAI_OPERATOR,
                    "X-IWO3-Client": FFAI_CLIENT,
                },
            )
        assert r.status_code == 404
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_evaluator_summary_checklist_contains_audit_rows() -> None:
    """Checklist should at least contain the seeded llm.invoked event."""
    wo_id = asyncio.run(_seed_wo("awaiting_operator"))
    try:
        asyncio.run(_seed_audit_review_event(wo_id, "pm_review"))
        with TestClient(app) as client:
            r = client.get(
                f"/work_orders/{wo_id}/evaluator_summary",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        checklist = r.json()["checklist"]
        assert any(c["action"] == "llm.invoked" for c in checklist)
    finally:
        asyncio.run(_drop_wo(wo_id))


# ── POST /work_orders/{id}/accept ──────────────────────────────────────


@iwo3_db
def test_accept_from_awaiting_operator_happy_path() -> None:
    wo_id = asyncio.run(_seed_wo("awaiting_operator"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/accept",
                json={"reason": "Deliverable looks good — shipping."},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["to"] == "completed"
        assert body["from"] == "awaiting_operator"
        events = asyncio.run(_audit_events_for(wo_id))
        assert "work_order.accepted" in events
        # Transition helper also writes work_order.transitioned (or a
        # routine event for the completed transition); both should be
        # present, distinguishable forensically.
        assert any(e.startswith("work_order.") for e in events)
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_accept_from_processing_happy_path() -> None:
    wo_id = asyncio.run(_seed_wo("processing"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/accept",
                json={"reason": "Accept mid-flight."},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        assert r.json()["to"] == "completed"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_accept_no_reason_still_works() -> None:
    """The reason field is optional. A default rationale is recorded."""
    wo_id = asyncio.run(_seed_wo("awaiting_operator"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/accept",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_accept_rejected_from_completed() -> None:
    """Cannot accept a WO that's already completed."""
    wo_id = asyncio.run(_seed_wo("completed"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/accept",
                json={"reason": "Trying to re-accept a completed WO."},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "not_acceptable"
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_accept_rejected_from_pending() -> None:
    """Pending WOs cannot be accepted — they haven't been dispatched."""
    wo_id = asyncio.run(_seed_wo("pending"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/accept",
                json={"reason": "Trying to accept pending."},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 409
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_accept_viewer_role_denied() -> None:
    wo_id = asyncio.run(_seed_wo("awaiting_operator"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/accept",
                json={"reason": "Viewer attempt."},
                headers={
                    "X-IWO3-User": KLEAR_VIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 403
    finally:
        asyncio.run(_drop_wo(wo_id))


@iwo3_db
def test_accept_cross_tenant_404() -> None:
    wo_id = asyncio.run(_seed_wo("awaiting_operator"))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/accept",
                json={"reason": "Tenant boundary probe."},
                headers={
                    "X-IWO3-User": FFAI_OPERATOR,
                    "X-IWO3-Client": FFAI_CLIENT,
                },
            )
        assert r.status_code == 404
    finally:
        asyncio.run(_drop_wo(wo_id))
