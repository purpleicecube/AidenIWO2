"""MegaLoop Beta-1 ε.2 / Q7 — /chat_sessions/me CRUD smoke tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


def test_chat_session_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.get("/chat_sessions/me")
    assert r.status_code == 401


@iwo3_db
def test_get_creates_empty_session_on_first_read() -> None:
    with TestClient(app) as client:
        r = client.get("/chat_sessions/me", headers=_hdr(KLEAR_OPERATOR))
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["messages"], list)
    assert isinstance(body["context"], dict)


@iwo3_db
def test_put_persists_messages_and_context() -> None:
    with TestClient(app) as client:
        r = client.put(
            "/chat_sessions/me",
            headers=_hdr(KLEAR_OPERATOR),
            json={
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ],
                "context": {"last_work_order_id": "wo-test"},
            },
        )
        assert r.status_code == 200, r.text
        # Re-fetch confirms persistence
        r2 = client.get(
            "/chat_sessions/me", headers=_hdr(KLEAR_OPERATOR)
        )
        body = r2.json()
        assert len(body["messages"]) == 2
        assert body["context"]["last_work_order_id"] == "wo-test"


@iwo3_db
def test_delete_clears_messages() -> None:
    with TestClient(app) as client:
        client.put(
            "/chat_sessions/me",
            headers=_hdr(KLEAR_OPERATOR),
            json={"messages": [{"role": "user", "content": "stale"}], "context": {}},
        )
        r = client.delete(
            "/chat_sessions/me", headers=_hdr(KLEAR_OPERATOR)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["messages"] == []
        assert body["context"] == {}


@iwo3_db
def test_per_user_isolation_within_tenant() -> None:
    """Owner and operator on the same tenant get distinct sessions."""
    with TestClient(app) as client:
        r1 = client.put(
            "/chat_sessions/me",
            headers=_hdr(KLEAR_OPERATOR),
            json={"messages": [{"role": "user", "content": "operator"}], "context": {}},
        )
        assert r1.status_code == 200
        r2 = client.get(
            "/chat_sessions/me", headers=_hdr(KLEAR_OWNER)
        )
        assert r2.status_code == 200
        # Owner's session is empty (or different); not the operator's payload.
        owner_msgs = r2.json()["messages"]
        if owner_msgs:
            assert owner_msgs[0].get("content") != "operator"
        # cleanup
        client.delete("/chat_sessions/me", headers=_hdr(KLEAR_OPERATOR))
        client.delete("/chat_sessions/me", headers=_hdr(KLEAR_OWNER))
