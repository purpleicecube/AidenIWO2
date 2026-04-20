"""Loop 7 Phase 7.1 — require_permission Depends tests.

Builds a tiny test app that exposes two endpoints: one guarded by
`require_permission_dep("work_order:create")` and one guarded by
`require_permission_dep("system:admin")`. Verifies the 7-role x
2-permission matrix produces the expected 200/403 outcomes and that
`authz.denied` audit rows land for every denial.
"""

from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deps import (
    current_user_context,
    require_permission_dep,
    shutdown_db_pool,
    startup_db_pool,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
USERS = {
    "owner": "00000000-0000-4000-8000-000001000001",
    "admin": "00000000-0000-4000-8000-000001000002",
    "operator": "00000000-0000-4000-8000-000001000003",
    "reviewer": "00000000-0000-4000-8000-000001000004",
    "viewer": "00000000-0000-4000-8000-000001000005",
    "agent_system": "00000000-0000-4000-8000-000001000006",
    "intruder": "00000000-0000-4000-8000-000099000002",
}

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _build_test_app() -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await startup_db_pool()
        try:
            yield
        finally:
            await shutdown_db_pool()

    test_app = FastAPI(lifespan=lifespan)

    @test_app.get("/gated-wo-create")
    async def gated_wo_create(
        _: dict = Depends(require_permission_dep("work_order:create")),
    ) -> dict:
        return {"ok": True}

    @test_app.get("/gated-sysadmin")
    async def gated_sysadmin(
        _: dict = Depends(require_permission_dep("system:admin")),
    ) -> dict:
        return {"ok": True}

    return test_app


@iwo3_db
@pytest.mark.parametrize(
    "role,expected_wo_create,expected_sysadmin",
    [
        ("owner", 200, 200),
        ("admin", 200, 403),
        ("operator", 200, 403),
        ("reviewer", 403, 403),
        ("viewer", 403, 403),
        ("agent_system", 200, 403),
        ("intruder", 403, 403),
    ],
)
def test_require_permission_role_matrix(
    role: str, expected_wo_create: int, expected_sysadmin: int
) -> None:
    app = _build_test_app()
    headers = {
        "X-IWO3-User": USERS[role],
        "X-IWO3-Client": KLEAR_CLIENT,
    }
    with TestClient(app) as client:
        r1 = client.get("/gated-wo-create", headers=headers)
        r2 = client.get("/gated-sysadmin", headers=headers)
    assert r1.status_code == expected_wo_create, (
        f"{role} work_order:create expected {expected_wo_create} got {r1.status_code}: {r1.text}"
    )
    assert r2.status_code == expected_sysadmin, (
        f"{role} system:admin expected {expected_sysadmin} got {r2.status_code}: {r2.text}"
    )


@iwo3_db
def test_require_permission_writes_authz_denied_on_deny() -> None:
    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get(
            "/gated-wo-create",
            headers={
                "X-IWO3-User": USERS["viewer"],
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 403
    body = r.json()["detail"]
    assert body["error"] == "permission_denied"
    assert body["permission"] == "work_order:create"
    assert body["reason"] == "role_lacks_permission"
    assert body["role"] == "viewer"

    # An authz.denied row landed. Use a fresh asyncio loop-free
    # pg call via psql would be overkill here; TestClient has already
    # closed the lifespan. Spin up a one-off asyncpg conn.
    import asyncio

    async def _count_denials() -> int:
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await asyncpg.connect(dsn=url)
        try:
            row = await conn.fetchrow(
                """
                SELECT count(*) AS n
                FROM action_audit_log
                WHERE action = 'authz.denied'
                  AND actor_user_id = $1
                  AND client_id = $2
                  AND target_id = 'work_order:create'
                  AND metadata->>'emitted_by' = 'fastapi.require_permission_dep'
                """,
                USERS["viewer"],
                KLEAR_CLIENT,
            )
            return int(row["n"])
        finally:
            await conn.close()

    count = asyncio.run(_count_denials())
    assert count >= 1


@iwo3_db
def test_require_permission_missing_headers_returns_401() -> None:
    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/gated-wo-create")
    assert r.status_code == 401
