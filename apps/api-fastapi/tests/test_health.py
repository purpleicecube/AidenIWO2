from datetime import datetime

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "iwo3-api-fastapi"
    assert body["version"]


def test_health_includes_uptime_fields() -> None:
    """System Health UI needs started_at + uptime_seconds for the
    Uptime KPI tile. Both fields must always be present and the
    monotonic uptime must be non-negative."""
    body = client.get("/healthz").json()
    assert "started_at" in body
    assert "uptime_seconds" in body
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0
    # started_at must be an ISO-8601 timestamp parseable by
    # datetime.fromisoformat — guards against format drift the UI
    # would otherwise render as a broken cell.
    datetime.fromisoformat(body["started_at"])
