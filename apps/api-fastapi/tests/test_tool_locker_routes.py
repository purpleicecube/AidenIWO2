"""MegaLoop Theta — Tools Locker route coverage.

Authn + RBAC + happy-path CRUD + skill-import path-traversal guard +
MCP test endpoint config-validation. The MCP test path against a real
stdio command is exercised in a separate integration suite (would
require an actual MCP server in CI); here we verify the route guards
on bad config without spawning a process.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


# ── Authn + RBAC gates ───────────────────────────────────────────


def test_create_tool_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog",
            json={
                "tool_key": "x",
                "display_name": "X",
                "description": "y",
                "category": "data",
                "runtime_status": "planned",
                "default_tier": "tier_2",
                "tool_type": "skill",
            },
        )
    assert r.status_code == 401


@iwo3_db
def test_create_tool_403_for_operator() -> None:
    """Operators have :read but not :create."""
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog",
            json={
                "tool_key": "operator_attempt",
                "display_name": "Operator Attempt",
                "description": "should be rejected",
                "category": "data",
                "runtime_status": "planned",
                "default_tier": "tier_2",
                "tool_type": "skill",
            },
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 403


@iwo3_db
def test_create_tool_422_invalid_category() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog",
            json={
                "tool_key": "bad_cat",
                "display_name": "Bad Cat",
                "description": "x",
                "category": "not_a_real_category",
                "runtime_status": "planned",
                "default_tier": "tier_2",
                "tool_type": "skill",
            },
            headers=_hdr(KLEAR_ADMIN),
        )
    assert r.status_code == 422


@iwo3_db
def test_create_tool_422_invalid_tool_key() -> None:
    """Tool keys must be lowercase + hyphen/underscore only."""
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog",
            json={
                "tool_key": "Has Spaces!",
                "display_name": "X",
                "description": "y",
                "category": "data",
                "runtime_status": "planned",
                "default_tier": "tier_2",
                "tool_type": "skill",
            },
            headers=_hdr(KLEAR_ADMIN),
        )
    assert r.status_code == 422


@iwo3_db
def test_create_then_update_then_delete_happy_path() -> None:
    tool_key = "theta_smoke_lifecycle"
    with TestClient(app) as client:
        # Create
        r = client.post(
            "/tool_catalog",
            json={
                "tool_key": tool_key,
                "display_name": "Theta Smoke Lifecycle",
                "description": "MegaLoop Theta route smoke",
                "category": "data",
                "runtime_status": "planned",
                "default_tier": "tier_2",
                "tool_type": "skill",
                "skill_content": "# Hi",
            },
            headers=_hdr(KLEAR_OWNER),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["tool_key"] == tool_key
        assert body["tool_type"] == "skill"
        assert body["skill_content"] == "# Hi"
        assert body["enabled"] is True

        # Duplicate -> 409
        r2 = client.post(
            "/tool_catalog",
            json={
                "tool_key": tool_key,
                "display_name": "Dup",
                "description": "x",
                "category": "data",
                "runtime_status": "planned",
                "default_tier": "tier_2",
                "tool_type": "skill",
            },
            headers=_hdr(KLEAR_OWNER),
        )
        assert r2.status_code == 409

        # Update — change description + enabled
        r3 = client.put(
            f"/tool_catalog/{tool_key}",
            json={"description": "Updated desc", "enabled": False},
            headers=_hdr(KLEAR_ADMIN),
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["description"] == "Updated desc"
        assert r3.json()["enabled"] is False

        # Update with invalid enum -> 422
        r4 = client.put(
            f"/tool_catalog/{tool_key}",
            json={"category": "ghosts"},
            headers=_hdr(KLEAR_ADMIN),
        )
        assert r4.status_code == 422

        # Delete
        r5 = client.delete(
            f"/tool_catalog/{tool_key}", headers=_hdr(KLEAR_OWNER)
        )
        assert r5.status_code == 204

        # Delete again -> 404
        r6 = client.delete(
            f"/tool_catalog/{tool_key}", headers=_hdr(KLEAR_OWNER)
        )
        assert r6.status_code == 404


@iwo3_db
def test_delete_tool_with_assignments_returns_409() -> None:
    """The seeded `web_search_brave` tool is assigned to several Klear
    sub-agents; deleting it must surface the 409 in_use error rather
    than tripping the FK RESTRICT."""
    with TestClient(app) as client:
        r = client.delete(
            "/tool_catalog/web_search_brave", headers=_hdr(KLEAR_OWNER)
        )
    assert r.status_code == 409
    body = r.json()
    detail = body["detail"]
    assert detail["error"] == "tool_in_use"


# ── Skill import ─────────────────────────────────────────────────


@iwo3_db
def test_list_available_skills_returns_filesystem_dirs() -> None:
    with TestClient(app) as client:
        r = client.get("/skills/available", headers=_hdr(KLEAR_ADMIN))
    assert r.status_code == 200
    body = r.json()
    # IWO2 ships .local/skills/ with at least pdf, pptx, docx, etc.
    # We don't assert specific names because IWO3_SKILLS_DIR override
    # may point elsewhere; just confirm the shape.
    assert "skills_dir" in body
    assert isinstance(body["skills"], list)


@iwo3_db
def test_import_skill_rejects_path_traversal() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/import_skill",
            json={"dir_name": "../etc"},
            headers=_hdr(KLEAR_ADMIN),
        )
    # Pydantic validator catches '..' upfront -> 422
    assert r.status_code == 422


@iwo3_db
def test_import_skill_rejects_slash() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/import_skill",
            json={"dir_name": "foo/bar"},
            headers=_hdr(KLEAR_ADMIN),
        )
    assert r.status_code == 422


@iwo3_db
def test_import_skill_404_when_dir_missing() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/import_skill",
            json={"dir_name": "no_such_skill_xyz"},
            headers=_hdr(KLEAR_ADMIN),
        )
    assert r.status_code == 404


@iwo3_db
def test_import_skill_403_for_operator() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/import_skill",
            json={"dir_name": "anything"},
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 403


@iwo3_db
def test_import_skill_happy_path_with_temp_skills_dir() -> None:
    """End-to-end import using a temp skills dir to keep the test
    hermetic. Creates a tiny SKILL.md, imports it, asserts the new
    tool_catalog row, then cleans up via DELETE."""
    tmp = tempfile.mkdtemp(prefix="iwo3-skills-")
    try:
        skill_dir = Path(tmp) / "theta-smoke-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: Theta Smoke\n"
            "description: A test skill imported by pytest\n"
            "---\n"
            "# Theta Smoke\n\n## Quick Start\nSay hello.\n",
            encoding="utf-8",
        )
        old = os.environ.get("IWO3_SKILLS_DIR")
        os.environ["IWO3_SKILLS_DIR"] = tmp
        try:
            with TestClient(app) as client:
                r = client.post(
                    "/tool_catalog/import_skill",
                    json={"dir_name": "theta-smoke-skill"},
                    headers=_hdr(KLEAR_ADMIN),
                )
                assert r.status_code == 201, r.text
                body = r.json()
                assert body["tool_key"] == "skill-theta-smoke-skill"
                assert body["tool_type"] == "skill"
                assert body["runtime_status"] == "skill_only"
                assert "Theta Smoke" in (body.get("skill_content") or "")
                # Re-import same dir -> 409
                r2 = client.post(
                    "/tool_catalog/import_skill",
                    json={"dir_name": "theta-smoke-skill"},
                    headers=_hdr(KLEAR_ADMIN),
                )
                assert r2.status_code == 409
                # Cleanup
                r3 = client.delete(
                    f"/tool_catalog/{body['tool_key']}",
                    headers=_hdr(KLEAR_ADMIN),
                )
                assert r3.status_code == 204
        finally:
            if old is None:
                os.environ.pop("IWO3_SKILLS_DIR", None)
            else:
                os.environ["IWO3_SKILLS_DIR"] = old
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── MCP test endpoint ────────────────────────────────────────────


@iwo3_db
def test_mcp_test_403_for_operator() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/mcp/test_connection",
            json={"mcp_config": {"transport": "stdio", "command": "echo"}},
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 403


@iwo3_db
def test_mcp_test_rejects_unsupported_transport() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/mcp/test_connection",
            json={"mcp_config": {"transport": "websocket"}},
            headers=_hdr(KLEAR_ADMIN),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["kind"] == "config_invalid"


@iwo3_db
def test_mcp_test_sse_returns_not_implemented_with_audit() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/mcp/test_connection",
            json={
                "mcp_config": {
                    "transport": "sse",
                    "url": "https://example.com/sse",
                }
            },
            headers=_hdr(KLEAR_ADMIN),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["kind"] == "sse_not_implemented"


@iwo3_db
def test_mcp_test_stdio_missing_command_returns_invalid() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/mcp/test_connection",
            json={"mcp_config": {"transport": "stdio"}},
            headers=_hdr(KLEAR_ADMIN),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["kind"] == "config_invalid"


@iwo3_db
def test_mcp_test_stdio_bad_command_surfaces_clean_error() -> None:
    """Spawn a non-existent binary; expect a clean error+kind back, not
    a 500."""
    with TestClient(app) as client:
        r = client.post(
            "/tool_catalog/mcp/test_connection",
            json={
                "mcp_config": {
                    "transport": "stdio",
                    "command": "this_binary_does_not_exist_xyz",
                    "args": [],
                }
            },
            headers=_hdr(KLEAR_ADMIN),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    # Either spawn_failed (FileNotFoundError) or timeout — both are clean.
    assert body["kind"] in {"spawn_failed", "timeout", "unexpected"}


# ── List endpoint extension ──────────────────────────────────────


@iwo3_db
def test_list_tool_catalog_includes_theta_fields() -> None:
    """Confirm the GET endpoint surfaces the MegaLoop Theta columns
    (tool_type + version_label + access_tier + governance fields)."""
    with TestClient(app) as client:
        r = client.get(
            "/tool_catalog?enabled=true", headers=_hdr(KLEAR_OPERATOR)
        )
    assert r.status_code == 200
    tools = r.json()["tools"]
    assert len(tools) >= 29
    # Pick a known seeded row and validate the new fields are non-null.
    brave = next((t for t in tools if t["tool_key"] == "web_search_brave"), None)
    assert brave is not None
    assert brave["tool_type"] in {
        "skill", "python_code", "slash_command", "cli", "api", "webhook",
        "mcp_server",
    }
    assert brave["version_label"] is not None
    assert brave["access_tier"] in {"any", "tier_1", "tier_2"}
    assert brave["max_concurrent"] is not None
    assert brave["default_lease_seconds"] is not None
