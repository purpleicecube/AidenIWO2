"""Loop 9 Phase 9.5 — GET /adapter_status/{key} tests.

Covers the 4-state Design Lab surface:
  - live_confirmed        env flag true + credential + first_invocation_confirmed_at
  - pending_confirmation  env flag true + credential + confirmed_at NULL
  - disabled              env flag false/unset (regardless of DB)
  - credential_missing    no adapter_credentials row
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


async def _set_credential_state(
    confirmed: bool, create_row: bool
) -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
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
        if create_row:
            if confirmed:
                await conn.execute(
                    """
                    INSERT INTO adapter_credentials
                      (client_id, adapter_catalog_id, credential_ref,
                       status, first_invocation_confirmed_at,
                       first_invocation_confirmed_by_user_id, notes)
                    VALUES ($1, $2, 'credential_ref:env:GAMMA_API_KEY',
                            'active', now(), $3,
                            'Seeded for Phase 9.5 status test')
                    """,
                    KLEAR_CLIENT,
                    catalog_id,
                    KLEAR_OPERATOR,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO adapter_credentials
                      (client_id, adapter_catalog_id, credential_ref,
                       status, notes)
                    VALUES ($1, $2, 'credential_ref:env:GAMMA_API_KEY',
                            'active', 'Seeded for Phase 9.5 status test')
                    """,
                    KLEAR_CLIENT,
                    catalog_id,
                )
    finally:
        await conn.close()


@iwo3_db
def test_status_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/adapter_status/gamma")
    assert r.status_code == 401


@iwo3_db
def test_status_live_confirmed() -> None:
    asyncio.run(_set_credential_state(confirmed=True, create_row=True))
    os.environ["GAMMA_LIVE_ENABLED"] = "true"
    try:
        with TestClient(app) as client:
            r = client.get(
                "/adapter_status/gamma",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "live_confirmed"
        assert body["env_flag_name"] == "GAMMA_LIVE_ENABLED"
        assert body["env_flag_enabled"] is True
        assert body["first_invocation_confirmed_at"] is not None
    finally:
        del os.environ["GAMMA_LIVE_ENABLED"]


@iwo3_db
def test_status_pending_confirmation() -> None:
    asyncio.run(_set_credential_state(confirmed=False, create_row=True))
    os.environ["GAMMA_LIVE_ENABLED"] = "true"
    try:
        with TestClient(app) as client:
            r = client.get(
                "/adapter_status/gamma",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending_confirmation"
    finally:
        del os.environ["GAMMA_LIVE_ENABLED"]


@iwo3_db
def test_status_disabled_when_flag_unset() -> None:
    asyncio.run(_set_credential_state(confirmed=True, create_row=True))
    os.environ.pop("GAMMA_LIVE_ENABLED", None)
    with TestClient(app) as client:
        r = client.get(
            "/adapter_status/gamma",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "disabled"
    assert body["env_flag_enabled"] is False


@iwo3_db
def test_status_credential_missing_when_no_row() -> None:
    asyncio.run(_set_credential_state(confirmed=False, create_row=False))
    os.environ["GAMMA_LIVE_ENABLED"] = "true"
    try:
        with TestClient(app) as client:
            r = client.get(
                "/adapter_status/gamma",
                headers={
                    "X-IWO3-User": KLEAR_OPERATOR,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "credential_missing"
    finally:
        del os.environ["GAMMA_LIVE_ENABLED"]
