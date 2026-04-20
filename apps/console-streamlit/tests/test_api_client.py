"""Loop 8 Phase 8.1 — smoke tests for the ApiClient.

Exercises /tenants + /work_orders + /permissions/check against the
live FastAPI app + Postgres. Streamlit UI rendering is covered by
`streamlit.testing.v1.AppTest` in a separate file.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

CONSOLE_DIR = Path(__file__).parent.parent
API_DIR = CONSOLE_DIR.parent / "api-fastapi"
API_PORT = int(os.environ.get("IWO3_API_PORT", "8765"))
API_BASE = f"http://127.0.0.1:{API_PORT}"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@pytest.fixture(scope="module")
def running_api():
    """Spin up the Loop 7 FastAPI app in a subprocess for the duration
    of the module. Uses a unique port so tests don't conflict with a
    dev server."""
    if not os.environ.get("IWO3_DATABASE_URL"):
        pytest.skip("IWO3_DATABASE_URL not set")

    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(API_PORT)],
        cwd=str(API_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Wait up to 10s for /healthz
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            r = httpx.get(f"{API_BASE}/healthz", timeout=0.5)
            if r.status_code == 200:
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("FastAPI did not come up on port " + str(API_PORT))

    yield API_BASE

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@iwo3_db
def test_api_client_lists_tenants(running_api: str) -> None:
    sys.path.insert(0, str(CONSOLE_DIR))
    from api_client import ApiClient

    api = ApiClient(
        base_url=running_api,
        user_id="00000000-0000-4000-8000-000001000003",
        client_id="00000000-0000-4000-8000-00000000c001",
    )
    tenants = api.list_tenants()
    assert any(t.designation == "IWO | Klear.ai" for t in tenants)


@iwo3_db
def test_api_client_lists_klear_work_orders(running_api: str) -> None:
    sys.path.insert(0, str(CONSOLE_DIR))
    from api_client import ApiClient

    api = ApiClient(
        base_url=running_api,
        user_id="00000000-0000-4000-8000-000001000003",
        client_id="00000000-0000-4000-8000-00000000c001",
    )
    wos = api.list_work_orders()
    assert len(wos) >= 1
    for wo in wos:
        assert wo.client_id == "00000000-0000-4000-8000-00000000c001"


@iwo3_db
def test_api_client_permission_check_roundtrip(running_api: str) -> None:
    sys.path.insert(0, str(CONSOLE_DIR))
    from api_client import ApiClient

    api = ApiClient(
        base_url=running_api,
        user_id="00000000-0000-4000-8000-000001000003",  # operator
        client_id="00000000-0000-4000-8000-00000000c001",
    )
    allowed = api.check_permission("work_order:create")
    assert allowed.allowed is True
    assert allowed.reason == "role_default"

    denied = api.check_permission("output_candidate:select")  # reviewer-only
    assert denied.allowed is False
    assert denied.reason == "role_lacks_permission"
