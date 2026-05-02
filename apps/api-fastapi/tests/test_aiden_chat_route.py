"""MegaLoop Alpha α.7 — /aiden/chat route smoke tests.

Covers the auth + RBAC + budget gates without burning real LLM tokens
(GROQ_API_KEY is intentionally unset → credential_missing path returns
200 ok=false, the contract for the browser to render).
"""

from __future__ import annotations

import os

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


def test_aiden_chat_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.post("/aiden/chat", json={"message": "hi"})
    assert r.status_code == 401


@iwo3_db
def test_aiden_chat_403_for_viewer() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/aiden/chat", json={"message": "hi"}, headers=_hdr(KLEAR_VIEWER)
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_aiden_chat_422_for_empty_message() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/aiden/chat", json={"message": ""}, headers=_hdr(KLEAR_OPERATOR)
        )
    assert r.status_code == 422, r.text


@iwo3_db
def test_aiden_chat_returns_credential_missing_when_groq_key_unset() -> None:
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/aiden/chat",
                json={"message": "Render the Klear pricing deck"},
                headers=_hdr(KLEAR_OPERATOR),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "credential_missing" in (body.get("error") or "")
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved


# 2026-05-01 — the three regex `_shortcut_reply` tests below were
# removed when Aiden Tier 1 gained a real `assistant_reply` decision
# kind. Capability / web-access / status prompts now flow through Aiden's
# CEO-voice LLM path instead of returning canned hardcoded headlines.
# Replaced with a single guard test: empty messages still short-circuit
# (no LLM tokens spent on whitespace).


@iwo3_db
def test_aiden_chat_empty_message_short_circuits_without_llm() -> None:
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/aiden/chat",
                json={"message": "   "},
                headers=_hdr(KLEAR_OPERATOR),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["decision_kind"] == "assistant_reply"
        # Empty-input fallback emits a short prompt-back, no LLM call.
        ar = body.get("assistant_reply") or {}
        assert "headline" in ar
        assert "message" in ar
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved
