"""Loop 9 Phase 9.1 — POST /adapter_credentials/{id}/confirm_first_invocation tests.

Covers admin-only gating, idempotent confirm, audit-row write, tenant scoping,
and 404 on missing credential. Uses self-contained credential rows so we
don't pollute the seed fixture set.
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
KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


async def _new_credential(client_id: str) -> str:
    """Insert a fresh adapter_credentials row for the gamma adapter and
    return its id. Reused across tests for isolation."""
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        # Resolve the gamma adapter_catalog id (seeded across tenants).
        cat_id = await conn.fetchval(
            "SELECT id FROM adapter_catalog WHERE adapter_key = 'gamma'"
        )
        cred_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO adapter_credentials
              (id, client_id, adapter_catalog_id, credential_ref, status)
            VALUES ($1, $2, $3, 'credential_ref:env:GAMMA_API_KEY_TEST', 'active')
            """,
            cred_id,
            client_id,
            cat_id,
        )
        return cred_id
    finally:
        await conn.close()


async def _drop_credential(cred_id: str) -> None:
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        await conn.execute(
            "DELETE FROM adapter_credentials WHERE id = $1",
            cred_id,
        )
    finally:
        await conn.close()


async def _audit_count_for(cred_id: str) -> int:
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        n = await conn.fetchval(
            """
            SELECT count(*)::int FROM action_audit_log
             WHERE action = 'adapter_credential.first_invocation_confirmed'
               AND target_id = $1
            """,
            cred_id,
        )
        return int(n)
    finally:
        await conn.close()


@iwo3_db
def test_confirm_requires_auth() -> None:
    cred_id = asyncio.run(_new_credential(KLEAR_CLIENT))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/adapter_credentials/{cred_id}/confirm_first_invocation",
                json={},
            )
        assert r.status_code == 401
    finally:
        asyncio.run(_drop_credential(cred_id))


@iwo3_db
def test_confirm_admin_only_operator_forbidden() -> None:
    # operator has work_order:create etc. but NOT adapter_credential:rotate
    # (Loop 4 §Q2 explicit exclusion).
    cred_id = asyncio.run(_new_credential(KLEAR_CLIENT))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/adapter_credentials/{cred_id}/confirm_first_invocation",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "permission_denied"
    finally:
        asyncio.run(_drop_credential(cred_id))


@iwo3_db
def test_confirm_admin_only_viewer_forbidden() -> None:
    cred_id = asyncio.run(_new_credential(KLEAR_CLIENT))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/adapter_credentials/{cred_id}/confirm_first_invocation",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_VIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 403
    finally:
        asyncio.run(_drop_credential(cred_id))


@iwo3_db
def test_confirm_first_call_sets_timestamp_and_audits() -> None:
    cred_id = asyncio.run(_new_credential(KLEAR_CLIENT))
    try:
        before_audit = asyncio.run(_audit_count_for(cred_id))
        assert before_audit == 0

        with TestClient(app) as client:
            r = client.post(
                f"/adapter_credentials/{cred_id}/confirm_first_invocation",
                json={"notes": "approved by Darrel for first prod test"},
                headers={
                    "X-IWO3-User": KLEAR_ADMIN,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["already_confirmed"] is False
        assert body["adapter_key"] == "gamma"
        assert body["first_invocation_confirmed_by_user_id"] == KLEAR_ADMIN
        # FastAPI returns the timestamp as a stringified asyncpg value.
        assert body["first_invocation_confirmed_at"] is not None
        assert body["notes"] == "approved by Darrel for first prod test"

        after_audit = asyncio.run(_audit_count_for(cred_id))
        assert after_audit == 1
    finally:
        asyncio.run(_drop_credential(cred_id))


@iwo3_db
def test_confirm_owner_can_also_confirm() -> None:
    cred_id = asyncio.run(_new_credential(KLEAR_CLIENT))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/adapter_credentials/{cred_id}/confirm_first_invocation",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_OWNER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        assert r.json()["already_confirmed"] is False
    finally:
        asyncio.run(_drop_credential(cred_id))


@iwo3_db
def test_confirm_idempotent_second_call() -> None:
    cred_id = asyncio.run(_new_credential(KLEAR_CLIENT))
    try:
        with TestClient(app) as client:
            r1 = client.post(
                f"/adapter_credentials/{cred_id}/confirm_first_invocation",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_ADMIN,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
            assert r1.status_code == 200
            assert r1.json()["already_confirmed"] is False

            r2 = client.post(
                f"/adapter_credentials/{cred_id}/confirm_first_invocation",
                json={"notes": "second call should be ignored"},
                headers={
                    "X-IWO3-User": KLEAR_ADMIN,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["already_confirmed"] is True
        # Same timestamp — no second update.
        assert (
            body2["first_invocation_confirmed_at"]
            == r1.json()["first_invocation_confirmed_at"]
        )

        # No new audit row — exactly one event in total.
        assert asyncio.run(_audit_count_for(cred_id)) == 1
    finally:
        asyncio.run(_drop_credential(cred_id))


@iwo3_db
def test_confirm_returns_404_for_unknown() -> None:
    fake_id = "00000000-0000-4000-8000-00000000d999"
    with TestClient(app) as client:
        r = client.post(
            f"/adapter_credentials/{fake_id}/confirm_first_invocation",
            json={},
            headers={
                "X-IWO3-User": KLEAR_ADMIN,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 404


@iwo3_db
def test_confirm_tenant_scoped_cannot_cross_tenants() -> None:
    # Klear admin tries to confirm a FFAI credential — RLS hides it,
    # route returns 404.
    ffai_cred_id = asyncio.run(_new_credential(FFAI_CLIENT))
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/adapter_credentials/{ffai_cred_id}/confirm_first_invocation",
                json={},
                headers={
                    "X-IWO3-User": KLEAR_ADMIN,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 404
    finally:
        asyncio.run(_drop_credential(ffai_cred_id))
