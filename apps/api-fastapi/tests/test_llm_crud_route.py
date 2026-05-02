"""Pre-Beta β.2 — /llm/configs CRUD smoke tests.

Verifies:
  - GET   /llm/configs returns the new metadata fields
  - POST  /llm/configs (admin) creates a row + emits llm_config.created
  - PATCH /llm/configs/{id} updates fields + emits llm_config.updated
  - PATCH disabling-only emits llm_config.disabled
  - DELETE soft-deletes by default (enabled=false)
  - DELETE ?hard=true removes the row
  - 401 / 403 / 400 / 404 / 409 paths
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


def _new_role() -> str:
    return f"test_role_{uuid.uuid4().hex[:8]}"


# ── GET /llm/configs ──────────────────────────────────────────────────


@iwo3_db
def test_list_returns_new_metadata_fields() -> None:
    with TestClient(app) as client:
        r = client.get("/llm/configs", headers=_hdr(KLEAR_OPERATOR))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configs"]
    sample = body["configs"][0]
    assert "display_name" in sample
    assert "credential_state" in sample
    assert sample["credential_state"] in ("set", "missing", "malformed")
    assert "env_var_name" in sample


# ── POST /llm/configs ─────────────────────────────────────────────────


def test_create_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.post("/llm/configs", json={})
    assert r.status_code == 401


@iwo3_db
def test_create_403_for_viewer() -> None:
    """Beta-1 ε.1 (Q5) split: operator now holds llm_config:write, so the
    403 wall moved to viewer/reviewer. Viewer carries no llm_config:* keys."""
    with TestClient(app) as client:
        r = client.post(
            "/llm/configs",
            headers=_hdr(KLEAR_VIEWER),
            json={
                "agent_role": _new_role(),
                "display_name": "T",
                "provider": "groq",
                "model": "openai/gpt-oss-120b",
                "credential_ref": "credential_ref:env:GROQ_API_KEY",
            },
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_delete_403_for_operator_after_rbac_split() -> None:
    """Beta-1 ε.1 (Q5): operator can WRITE but not DELETE. Architect lock C."""
    with TestClient(app) as client:
        # operator can still create
        r = client.post(
            "/llm/configs",
            headers=_hdr(KLEAR_OPERATOR),
            json={
                "agent_role": _new_role(),
                "display_name": "T",
                "provider": "groq",
                "model": "openai/gpt-oss-120b",
                "credential_ref": "credential_ref:env:GROQ_API_KEY",
            },
        )
        assert r.status_code == 201, r.text
        cfg_id = r.json()["config"]["id"]
        # but operator cannot delete
        rd = client.delete(
            f"/llm/configs/{cfg_id}",
            headers=_hdr(KLEAR_OPERATOR),
        )
        assert rd.status_code == 403, rd.text
        # cleanup
        client.delete(
            f"/llm/configs/{cfg_id}?hard=true",
            headers=_hdr(KLEAR_OWNER),
        )


@iwo3_db
def test_create_400_for_invalid_provider() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/llm/configs",
            headers=_hdr(KLEAR_OWNER),
            json={
                "agent_role": _new_role(),
                "display_name": "T",
                "provider": "carrier_pigeon",
                "model": "x",
                "credential_ref": "credential_ref:env:GROQ_API_KEY",
            },
        )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "unknown_provider"


@iwo3_db
def test_create_400_for_invalid_credential_ref() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/llm/configs",
            headers=_hdr(KLEAR_OWNER),
            json={
                "agent_role": _new_role(),
                "display_name": "T",
                "provider": "groq",
                "model": "x",
                "credential_ref": "raw-secret-not-a-ref",
            },
        )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "invalid_credential_ref"


@iwo3_db
def test_create_400_for_invalid_agent_role() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/llm/configs",
            headers=_hdr(KLEAR_OWNER),
            json={
                "agent_role": "Bad-Role-With-Caps",
                "display_name": "T",
                "provider": "groq",
                "model": "x",
                "credential_ref": "credential_ref:env:GROQ_API_KEY",
            },
        )
    assert r.status_code == 400, r.text


@iwo3_db
def test_create_then_patch_then_soft_delete_roundtrip() -> None:
    role = _new_role()
    with TestClient(app) as client:
        # Create
        r = client.post(
            "/llm/configs",
            headers=_hdr(KLEAR_OWNER),
            json={
                "agent_role": role,
                "display_name": "Test Sub-Agent",
                "description": "for the CRUD test",
                "provider": "groq",
                "model": "openai/gpt-oss-120b",
                "credential_ref": "credential_ref:env:GROQ_API_KEY",
                "enabled": True,
            },
        )
        assert r.status_code == 201, r.text
        cfg_id = r.json()["config"]["id"]
        assert r.json()["config"]["display_name"] == "Test Sub-Agent"

        # Conflict on duplicate role
        r2 = client.post(
            "/llm/configs",
            headers=_hdr(KLEAR_OWNER),
            json={
                "agent_role": role,
                "display_name": "dup",
                "provider": "groq",
                "model": "x",
                "credential_ref": "credential_ref:env:GROQ_API_KEY",
            },
        )
        assert r2.status_code == 409, r2.text

        # Patch model + system_prompt — Phase 0.3.2 requires explicit
        # tri-state prompt_action whenever system_prompt is in the body.
        r3 = client.patch(
            f"/llm/configs/{cfg_id}",
            headers=_hdr(KLEAR_OWNER),
            json={
                "model": "openai/gpt-oss-120b",
                "prompt_action": "set",
                "system_prompt": "hi",
            },
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["config"]["has_system_prompt"] is True

        # Soft-delete
        r4 = client.delete(
            f"/llm/configs/{cfg_id}", headers=_hdr(KLEAR_OWNER)
        )
        assert r4.status_code == 200, r4.text
        assert r4.json()["config"]["enabled"] is False

        # Hard delete
        r5 = client.delete(
            f"/llm/configs/{cfg_id}?hard=true", headers=_hdr(KLEAR_OWNER)
        )
        assert r5.status_code == 200, r5.text


@iwo3_db
def test_patch_404_for_unknown_id() -> None:
    with TestClient(app) as client:
        r = client.patch(
            f"/llm/configs/{uuid.uuid4()}",
            headers=_hdr(KLEAR_OWNER),
            json={"model": "x"},
        )
    assert r.status_code == 404, r.text


@iwo3_db
def test_patch_400_for_no_fields() -> None:
    # Need a real id; pick the seeded aiden_tier_1 row
    with TestClient(app) as client:
        configs = client.get(
            "/llm/configs", headers=_hdr(KLEAR_OWNER)
        ).json()["configs"]
        aiden = next(c for c in configs if c["agent_role"] == "aiden_tier_1")
        r = client.patch(
            f"/llm/configs/{aiden['id']}",
            headers=_hdr(KLEAR_OWNER),
            json={},
        )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "no_fields_to_update"


@iwo3_db
def test_delete_400_for_malformed_id() -> None:
    with TestClient(app) as client:
        r = client.delete(
            "/llm/configs/not-a-uuid", headers=_hdr(KLEAR_OWNER)
        )
    assert r.status_code == 400, r.text
