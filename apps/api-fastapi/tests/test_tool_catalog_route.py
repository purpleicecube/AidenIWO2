"""Loop Eta phase 1 — GET /tool_catalog route smoke tests.

Scope:
  - GET /tool_catalog returns all enabled rows (tenant-agnostic)
  - filter by `category` narrows to that category
  - filter by `runtime_status` narrows to that status
  - 403 when caller lacks `tool_catalog:read`

Self-seeding: Worker A's seed loader has not yet run in this worktree,
so each test inserts a fixed set of tool_catalog rows in setup and
removes them on teardown. The tests do NOT depend on any seeded
catalog content. They use unique `iwo2_origin` markers ('test-eta-c-*')
so the cleanup query can target only their rows.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict[str, str]:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


# Sentinel marker used in iwo2_origin — every test row carries this so
# teardown can DELETE only the rows we created without disturbing
# Worker A's seed when it lands.
_TEST_TAG = "test-eta-c"

_FIXTURES: list[dict] = [
    {
        "tool_key": "test_eta_c_brave_search",
        "display_name": "Test Brave Search",
        "description": "Worker C test fixture — Brave search.",
        "category": "search",
        "runtime_status": "runnable",
        "default_tier": "either",
        "tool_type": "api",
        "iwo2_origin": f"{_TEST_TAG}-brave",
    },
    {
        "tool_key": "test_eta_c_doc_summarize",
        "display_name": "Test Doc Summarize",
        "description": "Worker C test fixture — document summarize.",
        "category": "document",
        "runtime_status": "runnable",
        "default_tier": "tier_2",
        "tool_type": "python_code",
        "iwo2_origin": f"{_TEST_TAG}-doc",
    },
    {
        "tool_key": "test_eta_c_skill_template",
        "display_name": "Test Skill-Only Template",
        "description": "Worker C test fixture — skill-only template.",
        "category": "skill_only",
        "runtime_status": "catalog_only",
        "default_tier": "tier_1",
        "tool_type": "skill",
        "iwo2_origin": f"{_TEST_TAG}-skill",
    },
]


async def _seed_tool_catalog() -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        # Delete first in case a prior aborted run left rows.
        await conn.execute(
            "DELETE FROM tool_catalog WHERE iwo2_origin LIKE $1",
            f"{_TEST_TAG}-%",
        )
        for f in _FIXTURES:
            await conn.execute(
                """
                INSERT INTO tool_catalog
                  (tool_key, display_name, description,
                   category, runtime_status,
                   default_tier, tool_type, iwo2_origin, enabled)
                VALUES ($1, $2, $3,
                        $4::tool_category, $5::tool_runtime_status,
                        $6::tool_default_tier, $7::tool_type, $8, true)
                """,
                f["tool_key"],
                f["display_name"],
                f["description"],
                f["category"],
                f["runtime_status"],
                f["default_tier"],
                f["tool_type"],
                f["iwo2_origin"],
            )
    finally:
        await conn.close()


async def _purge_tool_catalog() -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        await conn.execute(
            "DELETE FROM tool_catalog WHERE iwo2_origin LIKE $1",
            f"{_TEST_TAG}-%",
        )
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def _seeded_tool_catalog() -> AsyncIterator[None]:
    if not os.environ.get("IWO3_DATABASE_URL"):
        yield
        return
    asyncio.run(_seed_tool_catalog())
    try:
        yield
    finally:
        asyncio.run(_purge_tool_catalog())


# ── tests ─────────────────────────────────────────────────────────────


@iwo3_db
def test_list_tool_catalog_returns_all_enabled_rows() -> None:
    with TestClient(app) as client:
        r = client.get("/tool_catalog", headers=_hdr(KLEAR_OWNER))
    assert r.status_code == 200, r.text
    body = r.json()
    keys = {row["tool_key"] for row in body["tools"]}
    for f in _FIXTURES:
        assert f["tool_key"] in keys
    # Sanity: returned rows carry the required shape.
    sample = next(
        row for row in body["tools"]
        if row["tool_key"] == "test_eta_c_brave_search"
    )
    assert sample["category"] == "search"
    assert sample["runtime_status"] == "runnable"
    assert sample["default_tier"] == "either"
    assert sample["enabled"] is True
    assert sample["iwo2_origin"] == f"{_TEST_TAG}-brave"
    assert "args_schema" in sample
    assert "description" in sample


@iwo3_db
def test_list_tool_catalog_filter_by_category_search() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/tool_catalog",
            headers=_hdr(KLEAR_OWNER),
            params={"category": "search"},
        )
    assert r.status_code == 200, r.text
    rows = r.json()["tools"]
    assert any(
        row["tool_key"] == "test_eta_c_brave_search" for row in rows
    )
    # Every returned row must have category=='search'.
    assert all(row["category"] == "search" for row in rows)
    # The non-search fixtures must not be in the result.
    keys = {row["tool_key"] for row in rows}
    assert "test_eta_c_doc_summarize" not in keys
    assert "test_eta_c_skill_template" not in keys


@iwo3_db
def test_list_tool_catalog_filter_by_runtime_status_catalog_only() -> None:
    """MegaLoop Theta D9.2 — `skill_only` retired in favour of
    `catalog_only` to keep runtime_status semantics on pure
    execution truth (vs the old vocabulary which mixed in `mcp`
    transport mode)."""
    with TestClient(app) as client:
        r = client.get(
            "/tool_catalog",
            headers=_hdr(KLEAR_OWNER),
            params={"runtime_status": "catalog_only"},
        )
    assert r.status_code == 200, r.text
    rows = r.json()["tools"]
    assert all(row["runtime_status"] == "catalog_only" for row in rows)
    keys = {row["tool_key"] for row in rows}
    assert "test_eta_c_skill_template" in keys
    assert "test_eta_c_brave_search" not in keys


@iwo3_db
def test_list_tool_catalog_filter_by_default_tier() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/tool_catalog",
            headers=_hdr(KLEAR_OWNER),
            params={"default_tier": "tier_2"},
        )
    assert r.status_code == 200, r.text
    rows = r.json()["tools"]
    assert all(row["default_tier"] == "tier_2" for row in rows)
    keys = {row["tool_key"] for row in rows}
    assert "test_eta_c_doc_summarize" in keys


def test_list_tool_catalog_401_without_headers() -> None:
    with TestClient(app) as client:
        r = client.get("/tool_catalog")
    assert r.status_code == 401


@iwo3_db
def test_list_tool_catalog_403_when_role_missing_permission() -> None:
    """Every seeded role currently carries `tool_catalog:read`. To
    exercise the 403 path we drop the role_permissions row for VIEWER
    inside the test, hit the route, then restore it. Mirrors the
    pattern used by `test_require_permission_dep` and keeps RBAC
    coverage honest without baking a permanent hole into the seed."""

    async def _drop_perm() -> None:
        conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
        try:
            await conn.execute(
                """
                DELETE FROM role_permissions
                 WHERE role = 'viewer'::membership_role
                   AND permission_id = (
                     SELECT id FROM permissions
                      WHERE permission_key = 'tool_catalog:read'
                   )
                """
            )
        finally:
            await conn.close()

    async def _restore_perm() -> None:
        conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
        try:
            await conn.execute(
                """
                INSERT INTO role_permissions (role, permission_id)
                SELECT 'viewer'::membership_role, p.id
                  FROM permissions p
                 WHERE p.permission_key = 'tool_catalog:read'
                ON CONFLICT DO NOTHING
                """
            )
        finally:
            await conn.close()

    asyncio.run(_drop_perm())
    try:
        with TestClient(app) as client:
            r = client.get("/tool_catalog", headers=_hdr(KLEAR_VIEWER))
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["detail"]["error"] == "permission_denied"
        assert body["detail"]["permission"] == "tool_catalog:read"
    finally:
        asyncio.run(_restore_perm())
