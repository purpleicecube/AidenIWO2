"""MegaLoop Beta-1 ε.3 / Q8 — server-side WO idempotency for chat creates."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


@iwo3_db
def test_chat_correlation_409_on_duplicate() -> None:
    """Beta-1 ε.3 / Q8 — second chat-driven create with same
    correlation_id returns 409 + the existing WO id."""
    correlation = f"chat:{uuid.uuid4().hex[:10]}"
    body = {
        "title": "First chat-driven WO",
        "description": "test",
        "type": "content_brief",
        "priority": "medium",
        "correlation_id": correlation,
    }
    with TestClient(app) as client:
        r1 = client.post("/work_orders", json=body, headers=_hdr(KLEAR_OWNER))
        assert r1.status_code == 200, r1.text
        first_id = r1.json()["id"]

        # Same correlation_id again → 409, never inserts a duplicate
        body2 = dict(body, title="Second attempt (should be rejected)")
        r2 = client.post("/work_orders", json=body2, headers=_hdr(KLEAR_OWNER))
        assert r2.status_code == 409, r2.text
        body_err = r2.json()["detail"]
        assert body_err["error"] == "duplicate_correlation_id"
        assert body_err["existing_work_order_id"] == first_id


@iwo3_db
def test_non_chat_correlation_does_not_collide() -> None:
    """Beta-1 ε.3 / Q8 — the partial UNIQUE only catches chat:* keys.
    Other correlations (telegram:, manual operator) keep their
    pre-Beta freedom to repeat."""
    correlation = f"telegram:test-{uuid.uuid4().hex[:6]}"
    body = {
        "title": "Telegram WO",
        "description": "tg",
        "type": "content_brief",
        "priority": "medium",
        "correlation_id": correlation,
    }
    with TestClient(app) as client:
        r1 = client.post("/work_orders", json=body, headers=_hdr(KLEAR_OWNER))
        r2 = client.post("/work_orders", json=body, headers=_hdr(KLEAR_OWNER))
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] != r2.json()["id"]
