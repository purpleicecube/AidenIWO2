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
