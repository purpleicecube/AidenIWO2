"""MegaLoop Beta-1 ε.4 / Q3 — webhook ingress smoke tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@iwo3_db
def test_webhook_telegram_rejects_unsigned_body() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/webhook/telegram",
            content=json.dumps({"update_id": 1}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["error"] == "webhook_signature_invalid"


@iwo3_db
def test_webhook_telegram_accepts_signed_body(monkeypatch) -> None:
    """HMAC-signed body verifies; tenant resolves; 200 returned."""
    secret = "test-webhook-hmac-32-bytes-minimum-okay"
    # Klear designation is "IWO | Klear.ai" → env suffix "KLEAR_AI"
    monkeypatch.setenv("IWO3_WEBHOOK_HMAC_KLEAR_AI", secret)

    body = json.dumps({"update_id": 99, "message": {
        "message_id": 1, "chat": {"id": 555}, "text": "/status xyz"
    }}).encode("utf-8")
    ts = str(int(time.time()))
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("ascii") + body,
        hashlib.sha256,
    ).hexdigest()

    with TestClient(app) as client:
        r = client.post(
            "/webhook/telegram",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-IWO3-Webhook-Signature": f"sha256={sig}",
                "X-IWO3-Webhook-Timestamp": ts,
            },
        )
    assert r.status_code == 200, r.text
    body_resp = r.json()
    assert body_resp["ok"] is True
    assert "verified_for_tenant=" in body_resp["detail"]


@iwo3_db
def test_webhook_telegram_rejects_expired_timestamp(monkeypatch) -> None:
    secret = "test-webhook-hmac-32-bytes-minimum-okay"
    monkeypatch.setenv("IWO3_WEBHOOK_HMAC_KLEAR_AI", secret)

    body = b'{"update_id":1}'
    ts = "1"  # epoch — way out of window
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("ascii") + body,
        hashlib.sha256,
    ).hexdigest()

    with TestClient(app) as client:
        r = client.post(
            "/webhook/telegram",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-IWO3-Webhook-Signature": f"sha256={sig}",
                "X-IWO3-Webhook-Timestamp": ts,
            },
        )
    assert r.status_code == 401, r.text


@iwo3_db
def test_webhook_telegram_native_secret_token(monkeypatch) -> None:
    """Telegram's literal-secret header should also resolve a tenant."""
    secret = "telegram-native-shared-secret-32b"
    monkeypatch.setenv("IWO3_WEBHOOK_HMAC_KLEAR_AI", secret)

    with TestClient(app) as client:
        r = client.post(
            "/webhook/telegram",
            content=b'{"update_id":2}',
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": secret,
            },
        )
    assert r.status_code == 200, r.text


@iwo3_db
def test_webhook_slack_returns_503() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/webhook/slack",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 503, r.text


# ── /health/channels + /health/llm ────────────────────────────────────


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


@iwo3_db
def test_health_channels_visible_for_operator() -> None:
    KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
    with TestClient(app) as client:
        r = client.get("/health/channels", headers=_hdr(KLEAR_OPERATOR))
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(c["channel_kind"] == "telegram" for c in body["channels"])


@iwo3_db
def test_health_llm_returns_credential_state_per_role() -> None:
    KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
    with TestClient(app) as client:
        r = client.get("/health/llm", headers=_hdr(KLEAR_OPERATOR))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["per_wo_ceiling"] >= 1000
    states = {c["credential_state"] for c in body["configs"]}
    assert states.issubset({"set", "missing", "malformed"})
