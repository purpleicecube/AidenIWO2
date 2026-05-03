"""Loop Eta phase 1 — /llm/configs/{id}/tools route smoke tests.

Scope:
  - GET returns full catalog joined with assignment state
    (assigned tools have assigned=true; others false)
  - PUT toggles enabled=true → audit `sub_agent.tool_granted` written
  - PUT toggles enabled=false → audit `sub_agent.tool_revoked` written
  - PUT on unknown tool_key → 404
  - PUT on cross-tenant llm_config → 404 (RLS hides)
  - 403 when caller lacks `sub_agent_tool:assign`

Self-seeding: tool_catalog rows are inserted/cleaned per test. The
seeded llm_configs `aiden_tier_1` for both KLEAR (c001) and FFAI (c002)
are reused — we never mutate them, only assign tools to them and clean
the assignments up.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, Optional

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"

FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
FFAI_OWNER = "00000000-0000-4000-8000-000002000001"

# Seeded llm_configs (see db/seeds/llm_configs.json).
KLEAR_AIDEN_TIER_1 = "00000000-0000-4000-8000-000091000001"
FFAI_AIDEN_TIER_1 = "00000000-0000-4000-8000-000092000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str, client_id: str = KLEAR_CLIENT) -> dict[str, str]:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": client_id}


_TEST_TAG = "test-eta-c-sat"

_FIXTURES: list[dict] = [
    {
        "tool_key": "test_eta_c_sat_search",
        "display_name": "Test SAT Search",
        "description": "Worker C sub-agent-tools fixture.",
        "category": "search",
        "runtime_status": "runnable",
        "default_tier": "either",
        "tool_type": "api",
        "iwo2_origin": f"{_TEST_TAG}-search",
    },
    {
        "tool_key": "test_eta_c_sat_render",
        "display_name": "Test SAT Render",
        "description": "Worker C sub-agent-tools fixture.",
        "category": "rendering",
        "runtime_status": "runnable",
        "default_tier": "tier_2",
        "tool_type": "python_code",
        "iwo2_origin": f"{_TEST_TAG}-render",
    },
]


async def _seed_tool_catalog() -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        await conn.execute(
            "DELETE FROM sub_agent_tools WHERE tool_key LIKE $1",
            "test_eta_c_sat_%",
        )
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


async def _purge() -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        # Always purge sub_agent_tools first because of the FK.
        await conn.execute(
            "DELETE FROM sub_agent_tools WHERE tool_key LIKE $1",
            "test_eta_c_sat_%",
        )
        await conn.execute(
            "DELETE FROM tool_catalog WHERE iwo2_origin LIKE $1",
            f"{_TEST_TAG}-%",
        )
    finally:
        await conn.close()


async def _last_audit_event_for_target(target_id: str) -> Optional[dict]:
    """Return the most recent action_audit_log row for a given
    sub_agent_tools id. `target_id` is varchar(128) in the audit
    schema, so no UUID cast is needed."""
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        row = await conn.fetchrow(
            """
            SELECT action, target_type, target_id,
                   metadata::text AS metadata
              FROM action_audit_log
             WHERE target_id = $1
             ORDER BY created_at DESC, id DESC
             LIMIT 1
            """,
            target_id,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def _seeded_catalog() -> AsyncIterator[None]:
    if not os.environ.get("IWO3_DATABASE_URL"):
        yield
        return
    asyncio.run(_seed_tool_catalog())
    try:
        yield
    finally:
        asyncio.run(_purge())


# ── GET /llm/configs/{id}/tools ───────────────────────────────────────


@iwo3_db
def test_get_returns_catalog_joined_with_assignments() -> None:
    with TestClient(app) as client:
        # Pre-assign one fixture to verify the LEFT JOIN surfaces it.
        r_put = client.put(
            f"/llm/configs/{KLEAR_AIDEN_TIER_1}/tools/test_eta_c_sat_search",
            headers=_hdr(KLEAR_OWNER),
            json={"enabled": True, "notes": "from test"},
        )
        assert r_put.status_code == 200, r_put.text

        r = client.get(
            f"/llm/configs/{KLEAR_AIDEN_TIER_1}/tools",
            headers=_hdr(KLEAR_OWNER),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_config_id"] == KLEAR_AIDEN_TIER_1
    assert body["agent_role"] == "aiden_tier_1"

    by_key = {row["tool_key"]: row for row in body["tools"]}
    # Both fixtures must be in the response (full catalog joined).
    assert "test_eta_c_sat_search" in by_key
    assert "test_eta_c_sat_render" in by_key

    # The pre-assigned tool surfaces with assigned=true, enabled=true.
    assigned = by_key["test_eta_c_sat_search"]
    assert assigned["assigned"] is True
    assert assigned["enabled"] is True
    assert assigned["granted_at"] is not None
    assert assigned["granted_by_user_id"] == KLEAR_OWNER
    assert assigned["notes"] == "from test"

    # The unassigned tool surfaces with assigned=false, enabled=false.
    unassigned = by_key["test_eta_c_sat_render"]
    assert unassigned["assigned"] is False
    assert unassigned["enabled"] is False
    assert unassigned["granted_at"] is None
    assert unassigned["granted_by_user_id"] is None


@iwo3_db
def test_get_404_for_cross_tenant_llm_config() -> None:
    """KLEAR caller asks for FFAI's llm_config — RLS hides the row,
    route 404s."""
    with TestClient(app) as client:
        r = client.get(
            f"/llm/configs/{FFAI_AIDEN_TIER_1}/tools",
            headers=_hdr(KLEAR_OWNER),
        )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "llm_config_not_found"


# ── PUT /llm/configs/{id}/tools/{tool_key} ────────────────────────────


@iwo3_db
def test_put_grant_writes_tool_granted_audit() -> None:
    with TestClient(app) as client:
        r = client.put(
            f"/llm/configs/{KLEAR_AIDEN_TIER_1}/tools/test_eta_c_sat_search",
            headers=_hdr(KLEAR_OWNER),
            json={"enabled": True, "notes": "grant"},
        )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["enabled"] is True
    assert row["llm_config_id"] == KLEAR_AIDEN_TIER_1
    assert row["tool_key"] == "test_eta_c_sat_search"
    assert row["notes"] == "grant"
    assert row["granted_by_user_id"] == KLEAR_OWNER

    audit = asyncio.run(_last_audit_event_for_target(row["id"]))
    assert audit is not None
    assert audit["action"] == "sub_agent.tool_granted"
    assert audit["target_type"] == "sub_agent_tool"


@iwo3_db
def test_put_revoke_writes_tool_revoked_audit() -> None:
    with TestClient(app) as client:
        # First grant so there is something to revoke.
        r1 = client.put(
            f"/llm/configs/{KLEAR_AIDEN_TIER_1}/tools/test_eta_c_sat_render",
            headers=_hdr(KLEAR_OWNER),
            json={"enabled": True},
        )
        assert r1.status_code == 200, r1.text
        # Now revoke (soft).
        r2 = client.put(
            f"/llm/configs/{KLEAR_AIDEN_TIER_1}/tools/test_eta_c_sat_render",
            headers=_hdr(KLEAR_OWNER),
            json={"enabled": False, "notes": "revoking"},
        )
    assert r2.status_code == 200, r2.text
    row = r2.json()
    assert row["enabled"] is False
    assert row["notes"] == "revoking"

    audit = asyncio.run(_last_audit_event_for_target(row["id"]))
    assert audit is not None
    assert audit["action"] == "sub_agent.tool_revoked"


@iwo3_db
def test_put_404_for_unknown_tool_key() -> None:
    with TestClient(app) as client:
        r = client.put(
            f"/llm/configs/{KLEAR_AIDEN_TIER_1}/tools/no_such_tool_xyz",
            headers=_hdr(KLEAR_OWNER),
            json={"enabled": True},
        )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "tool_not_in_catalog"


@iwo3_db
def test_put_404_for_cross_tenant_llm_config() -> None:
    """KLEAR caller tries to assign a tool to FFAI's llm_config — RLS
    hides the FFAI row so the route's existence check returns None and
    the route 404s. We must not leak a FK-violation 500."""
    with TestClient(app) as client:
        r = client.put(
            f"/llm/configs/{FFAI_AIDEN_TIER_1}/tools/test_eta_c_sat_search",
            headers=_hdr(KLEAR_OWNER),
            json={"enabled": True},
        )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "llm_config_not_found"


@iwo3_db
def test_put_403_when_caller_lacks_assign_permission() -> None:
    """`sub_agent_tool:assign` is owner+admin only. Operator role is
    seeded with `sub_agent_tool:read` but not `:assign`, so an operator
    PUT must fail with 403 + emit `authz.denied`."""
    with TestClient(app) as client:
        r = client.put(
            f"/llm/configs/{KLEAR_AIDEN_TIER_1}/tools/test_eta_c_sat_search",
            headers=_hdr(KLEAR_OPERATOR),
            json={"enabled": True},
        )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["detail"]["error"] == "permission_denied"
    assert body["detail"]["permission"] == "sub_agent_tool:assign"


@iwo3_db
def test_get_works_inside_ffai_tenant() -> None:
    """Sanity: same route works for FFAI tenant when called with FFAI
    headers. Confirms the RLS scope is on the caller's tenant, not a
    hardcoded c001."""
    with TestClient(app) as client:
        r = client.get(
            f"/llm/configs/{FFAI_AIDEN_TIER_1}/tools",
            headers=_hdr(FFAI_OWNER, client_id=FFAI_CLIENT),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_config_id"] == FFAI_AIDEN_TIER_1
    assert body["agent_role"] == "aiden_tier_1"
    # Catalog rows must surface even if no assignment exists yet.
    keys = {row["tool_key"] for row in body["tools"]}
    assert "test_eta_c_sat_search" in keys
