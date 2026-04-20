"""Loop 7 Phase 7.3 — candidate review + audit log + permissions/check route tests."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app

KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_REVIEWER = "00000000-0000-4000-8000-000001000004"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"
KLEAR_PPTX_TEMPLATE = "00000000-0000-4000-8000-000010000001"

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


async def _seed_candidate_group() -> tuple[str, str, list[str]]:
    """Insert a fresh package + 3 candidate handoffs. Returns
    (package_id, group_id, [handoff_a, handoff_b, handoff_c])."""
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        package_id = str(uuid.uuid4())
        group_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO output_packages
              (id, client_id, output_kind, title, content_blocks,
               template_profile_id, created_by_user_id, provenance)
            VALUES ($1, $2, 'gamma_pptx', 'phase-7.3 route test',
                    $3::jsonb, $4, $5, $6::jsonb)
            """,
            package_id,
            KLEAR_CLIENT,
            json.dumps({"sections": [{"title": "t", "body": "b"}]}),
            KLEAR_PPTX_TEMPLATE,
            KLEAR_OPERATOR,
            json.dumps({"test_marker": "phase-7.3-route"}),
        )
        handoff_ids: list[str] = []
        for _ in range(3):
            hid = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO output_handoffs
                  (id, client_id, output_package_id, status,
                   candidate_group_id, candidate_status, metadata)
                VALUES ($1, $2, $3, 'queued', $4, 'candidate', $5::jsonb)
                """,
                hid,
                KLEAR_CLIENT,
                package_id,
                group_id,
                json.dumps({"test_marker": "phase-7.3-route"}),
            )
            handoff_ids.append(hid)
        return package_id, group_id, handoff_ids
    finally:
        await conn.close()


async def _drop_candidates(package_id: str, handoff_ids: list[str]) -> None:
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        await conn.execute(
            """
            DELETE FROM action_audit_log
            WHERE metadata->>'test_marker' = 'phase-7.3-route'
               OR target_id = ANY($1)
               OR target_id = $2
            """,
            handoff_ids,
            package_id,
        )
        await conn.execute(
            "DELETE FROM output_handoffs WHERE id = ANY($1)",
            handoff_ids,
        )
        await conn.execute(
            "DELETE FROM output_packages WHERE id = $1", package_id
        )
    finally:
        await conn.close()


@iwo3_db
def test_reviewer_selects_candidate_end_to_end() -> None:
    package_id, _group, handoffs = asyncio.run(_seed_candidate_group())
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/output_handoffs/{handoffs[0]}/select_candidate",
                json={"reason": "clearest framing"},
                headers={
                    "X-IWO3-User": KLEAR_REVIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["selected_handoff_id"] == handoffs[0]
        assert sorted(body["rejected_sibling_ids"]) == sorted(handoffs[1:])
        assert body["package_validated"] == package_id
    finally:
        asyncio.run(_drop_candidates(package_id, handoffs))


@iwo3_db
def test_operator_cannot_select_candidate() -> None:
    package_id, _group, handoffs = asyncio.run(_seed_candidate_group())
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/output_handoffs/{handoffs[0]}/select_candidate",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 403
        assert (
            r.json()["detail"]["permission"] == "output_candidate:select"
        )
    finally:
        asyncio.run(_drop_candidates(package_id, handoffs))


@iwo3_db
def test_reject_candidate_preserves_siblings_and_package() -> None:
    package_id, _group, handoffs = asyncio.run(_seed_candidate_group())
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/output_handoffs/{handoffs[1]}/reject_candidate",
                json={"reason": "off-brand"},
                headers={
                    "X-IWO3-User": KLEAR_REVIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200
        body = r.json()
        assert body["rejected_handoff_id"] == handoffs[1]
    finally:
        asyncio.run(_drop_candidates(package_id, handoffs))


@iwo3_db
def test_permissions_check_reflects_role_grants() -> None:
    with TestClient(app) as client:
        # Operator holds work_order:create
        r1 = client.get(
            "/permissions/check",
            params={"permission": "work_order:create"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
        assert r1.status_code == 200
        assert r1.json()["allowed"] is True
        assert r1.json()["reason"] == "role_default"
        assert r1.json()["role"] == "operator"

        # Operator lacks output_candidate:select (reviewer-only)
        r2 = client.get(
            "/permissions/check",
            params={"permission": "output_candidate:select"},
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
        assert r2.status_code == 200
        assert r2.json()["allowed"] is False
        assert r2.json()["reason"] == "role_lacks_permission"

        # Viewer denied on system:admin
        r3 = client.get(
            "/permissions/check",
            params={"permission": "system:admin"},
            headers={
                "X-IWO3-User": KLEAR_VIEWER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
        assert r3.status_code == 200
        assert r3.json()["allowed"] is False


@iwo3_db
def test_audit_log_requires_owner_permission() -> None:
    with TestClient(app) as client:
        # Operator lacks audit_log:read
        r_op = client.get(
            "/audit_log",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
        assert r_op.status_code == 403

        # Owner can read
        r_own = client.get(
            "/audit_log",
            headers={
                "X-IWO3-User": KLEAR_OWNER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
            params={"limit": 5},
        )
        assert r_own.status_code == 200
        body: dict[str, Any] = r_own.json()
        assert "audit_rows" in body
        # Every row scoped to Klear tenant via RLS.
        for row in body["audit_rows"]:
            assert row["client_id"] == KLEAR_CLIENT
