"""Loop 7 Phase 7.1 — /tenants route tests.

Uses FastAPI's TestClient against the live aiden_iwo3 database. Every
test supplies the dev bearer headers (X-IWO3-User + X-IWO3-Client)
matching a seeded user + tenant.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from main import app

KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
SUPER = "00000000-0000-4000-8000-000099000001"
INTRUDER = "00000000-0000-4000-8000-000099000002"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set — integration tests require the live DB",
)


@iwo3_db
def test_tenants_requires_auth_headers() -> None:
    with TestClient(app) as client:
        r = client.get("/tenants")
    assert r.status_code == 401


@iwo3_db
def test_tenants_klear_operator_sees_only_klear() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/tenants",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200
    tenants = r.json()["tenants"]
    designations = {t["designation"] for t in tenants}
    assert designations == {"IWO | Klear.ai"}
    assert tenants[0]["role"] == "operator"


@iwo3_db
def test_tenants_super_sees_both_tenants() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/tenants",
            headers={
                "X-IWO3-User": SUPER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200
    designations = sorted(t["designation"] for t in r.json()["tenants"])
    assert designations == ["IWO | FreedomForge.AI", "IWO | Klear.ai"]


@iwo3_db
def test_tenants_intruder_sees_no_tenants() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/tenants",
            headers={
                "X-IWO3-User": INTRUDER,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200
    assert r.json()["tenants"] == []


@iwo3_db
def test_readyz_connects_to_database() -> None:
    with TestClient(app) as client:
        r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "connected"}
