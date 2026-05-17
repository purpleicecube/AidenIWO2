"""Pre-Beta β.3 — /dispatch route smoke tests.

Covers the auth + RBAC + WO lookup paths without burning real LLM
tokens. The Aiden + Tier 2 calls bottom out at credential_missing
when GROQ_API_KEY isn't set, which is the operator-readable failure
contract for empty-env CI runs.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


def test_dispatch_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.post(
            f"/work_orders/{uuid.uuid4()}/dispatch", json={}
        )
    assert r.status_code == 401


@iwo3_db
def test_dispatch_403_for_viewer() -> None:
    with TestClient(app) as client:
        r = client.post(
            f"/work_orders/{uuid.uuid4()}/dispatch",
            json={},
            headers=_hdr(KLEAR_VIEWER),
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_dispatch_404_for_unknown_wo() -> None:
    with TestClient(app) as client:
        r = client.post(
            f"/work_orders/{uuid.uuid4()}/dispatch",
            json={},
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 404, r.text


@iwo3_db
def test_dispatch_400_for_malformed_wo_id() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/work_orders/not-a-uuid/dispatch",
            json={},
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 400, r.text


@iwo3_db
def test_dispatch_known_wo_returns_credential_missing_when_groq_unset() -> None:
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        with TestClient(app) as client:
            wo = client.get(
                "/work_orders", headers=_hdr(KLEAR_OPERATOR)
            ).json()["work_orders"][0]
            r = client.post(
                f"/work_orders/{wo['id']}/dispatch",
                json={},
                headers=_hdr(KLEAR_OPERATOR),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "credential_missing" in (body.get("error") or "")
        assert body["work_order_id"] == wo["id"]
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved


@iwo3_db
def test_dispatch_overrides_assistant_reply_when_requested_outputs_explicit() -> None:
    """FF.AI Hotfix (2026-05-17) regression — when Aiden Tier 1 returns
    `assistant_reply` but the WO carries explicit
    requested_outputs.{output_kind, template_profile_id}, the dispatcher
    treats the operator's explicit signal as authoritative and overrides
    decision_kind to `work_order_brief`. Asserts:

    1. Response decision_kind is `work_order_brief` (not assistant_reply)
    2. The override audit event was written to action_audit_log
    """
    import asyncio
    import asyncpg
    from unittest.mock import patch

    from runtime.tier_1_aiden import (
        AidenAssistantReply,
        AidenDecision,
    )
    from runtime.tier_2_subagents import Tier2Error

    KLEAR_PDF_TEMPLATE = "00000000-0000-4000-8000-000010000002"
    klear_uuid = uuid.UUID(KLEAR_CLIENT)
    operator_uuid = uuid.UUID(KLEAR_OPERATOR)
    wo_id = str(uuid.uuid4())

    async def _seed_wo_with_explicit_outputs() -> None:
        conn = await asyncpg.connect(os.environ["IWO3_DATABASE_URL"])
        try:
            await conn.execute(
                """
                INSERT INTO work_orders
                  (id, client_id, title, description, type, priority,
                   status, requested_outputs, submitted_by_user_id)
                VALUES ($1::uuid, $2::uuid, $3, $4, 'decision_request',
                        'medium', 'pending', $5::jsonb, $6::uuid)
                """,
                wo_id,
                klear_uuid,
                "REPORT ON something — chatty intake",
                "Tell me about hosted repair smoke testing.",
                f'{{"output_kind":"pdf","template_profile_id":"{KLEAR_PDF_TEMPLATE}"}}',
                operator_uuid,
            )
        finally:
            await conn.close()

    async def _read_audit_count() -> int:
        conn = await asyncpg.connect(os.environ["IWO3_DATABASE_URL"])
        try:
            return await conn.fetchval(
                """
                SELECT count(*)::int
                FROM action_audit_log
                WHERE target_id = $1
                  AND action = 'aiden.dispatch_overridden_by_requested_outputs'
                """,
                wo_id,
            )
        finally:
            await conn.close()

    async def _cleanup() -> None:
        conn = await asyncpg.connect(os.environ["IWO3_DATABASE_URL"])
        try:
            await conn.execute(
                "DELETE FROM action_audit_log WHERE target_id = $1",
                wo_id,
            )
            await conn.execute(
                "DELETE FROM work_orders WHERE id = $1::uuid", wo_id
            )
        finally:
            await conn.close()

    asyncio.run(_seed_wo_with_explicit_outputs())

    async def _fake_aiden(*args, **kwargs):
        return AidenDecision(
            decision_kind="assistant_reply",
            title="Chatty title from Aiden",
            summary="Aiden's summary",
            assistant_reply=AidenAssistantReply(
                headline="A long assistant_reply that would normally bail",
                message=(
                    "Aiden produced this long markdown reply instead of "
                    "dispatching to Tier 2 — the override should treat "
                    "the explicit requested_outputs as authoritative."
                ),
                suggested_requests=[],
            ),
            provider="groq",
            model="openai/gpt-oss-120b",
            latency_ms=500,
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
        )

    async def _fake_tier_2(*args, **kwargs):
        raise Tier2Error(
            "tier_2_stub", "intentional stub — we only care about override"
        )

    try:
        with patch(
            "routes.dispatch.invoke_aiden_tier_1", _fake_aiden
        ), patch(
            "routes.dispatch.invoke_tier_2", _fake_tier_2
        ):
            with TestClient(app) as client:
                r = client.post(
                    f"/work_orders/{wo_id}/dispatch",
                    json={},
                    headers=_hdr(KLEAR_OPERATOR),
                )
        assert r.status_code == 200, r.text
        body = r.json()
        # Override flipped assistant_reply → work_order_brief; the
        # downstream branded-intent classifier may further promote to
        # workflow_brief when the WO matches a branded chain. Either
        # is acceptable — what matters is that we are NOT in the
        # assistant_reply early-exit anymore.
        assert body["decision_kind"] in ("work_order_brief", "workflow_brief"), (
            f"override should have flipped decision_kind out of "
            f"assistant_reply; got body={body}"
        )
        audit_rows = asyncio.run(_read_audit_count())
        assert audit_rows == 1, (
            f"expected 1 override audit row, got {audit_rows}"
        )
    finally:
        asyncio.run(_cleanup())


@iwo3_db
def test_run_next_step_404_for_unknown_execution() -> None:
    # KLEAR_OWNER carries workflow_step_run:update; operator currently
    # only has :read.
    with TestClient(app) as client:
        r = client.post(
            f"/workflows/{uuid.uuid4()}/run_next_step",
            headers=_hdr(KLEAR_OWNER),
        )
    assert r.status_code == 404, r.text


@iwo3_db
def test_run_next_step_400_for_malformed_id() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/workflows/not-a-uuid/run_next_step",
            headers=_hdr(KLEAR_OWNER),
        )
    assert r.status_code == 400, r.text


@iwo3_db
def test_run_next_step_403_for_viewer() -> None:
    with TestClient(app) as client:
        r = client.post(
            f"/workflows/{uuid.uuid4()}/run_next_step",
            headers=_hdr(KLEAR_VIEWER),
        )
    assert r.status_code == 403, r.text


def test_run_next_step_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.post(f"/workflows/{uuid.uuid4()}/run_next_step")
    assert r.status_code == 401
