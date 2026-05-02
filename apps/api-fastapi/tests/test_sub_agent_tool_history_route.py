"""Loop Eta phase 1.1 — /llm/configs/{id}/tool_history route tests.

Scope:
  - GET returns recent sub_agent.tool_* runtime events scoped to one
    llm_config via metadata.llm_config_id
  - cross-tenant llm_config id returns 404
  - 403 when caller lacks audit_log:read
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"

MARK_TIER_2_LLM_CONFIG_ID = "00000000-0000-4000-8000-000091000003"
FFAI_AIDEN_TIER_1 = "00000000-0000-4000-8000-000092000001"

_TEST_TAG = "test-eta-tool-history"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str, client_id: str = KLEAR_CLIENT) -> dict[str, str]:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": client_id}


async def _seed_history_rows() -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        wo_one = f"{_TEST_TAG}-wo-1"
        wo_two = f"{_TEST_TAG}-wo-2"
        unrelated = f"{_TEST_TAG}-other"
        rows = [
            (
                KLEAR_CLIENT,
                KLEAR_OWNER,
                "sub_agent.tool_called",
                "aiden_tool",
                "runtime_health",
                {
                    "tool_name": "runtime_health",
                    "agent_role": "mark_tier_2",
                    "llm_config_id": MARK_TIER_2_LLM_CONFIG_ID,
                    "work_order_id": wo_one,
                    "iteration_index": 1,
                    "result_size_chars": 123,
                },
            ),
            (
                KLEAR_CLIENT,
                KLEAR_OWNER,
                "sub_agent.tool_unauthorized",
                "aiden_tool",
                "stitch_design",
                {
                    "tool_name": "stitch_design",
                    "agent_role": "mark_tier_2",
                    "llm_config_id": MARK_TIER_2_LLM_CONFIG_ID,
                    "work_order_id": wo_two,
                    "iteration_index": 2,
                    "detail": "tool not assigned",
                },
            ),
            (
                KLEAR_CLIENT,
                KLEAR_OWNER,
                "sub_agent.tool_called",
                "aiden_tool",
                "runtime_health",
                {
                    "tool_name": "runtime_health",
                    "agent_role": "mark_tier_2",
                    "llm_config_id": "00000000-0000-4000-8000-000091000004",
                    "work_order_id": unrelated,
                    "iteration_index": 1,
                },
            ),
        ]
        for client_id, actor_user_id, action, target_type, target_id, md in rows:
            await conn.execute(
                """
                INSERT INTO action_audit_log
                  (client_id, actor_user_id, action,
                   target_type, target_id, metadata)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb)
                """,
                client_id,
                actor_user_id,
                action,
                target_type,
                target_id,
                json.dumps(md),
            )
    finally:
        await conn.close()


async def _purge_history_rows() -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        await conn.execute(
            """
            DELETE FROM action_audit_log
             WHERE metadata->>'work_order_id' LIKE $1
            """,
            f"{_TEST_TAG}-%",
        )
    finally:
        await conn.close()


async def _drop_viewer_audit_perm() -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        await conn.execute(
            """
            DELETE FROM role_permissions
             WHERE role = 'viewer'::membership_role
               AND permission_id = (
                 SELECT id FROM permissions
                  WHERE permission_key = 'audit_log:read'
               )
            """
        )
    finally:
        await conn.close()


async def _restore_viewer_audit_perm() -> None:
    conn = await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])
    try:
        await conn.execute(
            """
            INSERT INTO role_permissions (role, permission_id)
            SELECT 'viewer'::membership_role, id
              FROM permissions
             WHERE permission_key = 'audit_log:read'
               AND NOT EXISTS (
                 SELECT 1
                   FROM role_permissions
                  WHERE role = 'viewer'::membership_role
                    AND permission_id = permissions.id
               )
            """
        )
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def _seeded_history() -> AsyncIterator[None]:
    if not os.environ.get("IWO3_DATABASE_URL"):
        yield
        return
    asyncio.run(_seed_history_rows())
    try:
        yield
    finally:
        asyncio.run(_purge_history_rows())


@iwo3_db
def test_get_tool_history_returns_only_matching_llm_config_events() -> None:
    with TestClient(app) as client:
        r = client.get(
            f"/llm/configs/{MARK_TIER_2_LLM_CONFIG_ID}/tool_history",
            headers=_hdr(KLEAR_OWNER),
            params={"limit": 10},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_config_id"] == MARK_TIER_2_LLM_CONFIG_ID
    assert body["agent_role"] == "mark_tier_2"
    entries = body["entries"]
    assert len(entries) == 2
    actions = {entry["action"] for entry in entries}
    assert "sub_agent.tool_called" in actions
    assert "sub_agent.tool_unauthorized" in actions
    tool_names = {entry["tool_name"] for entry in entries}
    assert "runtime_health" in tool_names
    assert "stitch_design" in tool_names
    assert all(
        entry["metadata"]["llm_config_id"] == MARK_TIER_2_LLM_CONFIG_ID
        for entry in entries
    )


@iwo3_db
def test_get_tool_history_404_for_cross_tenant_config() -> None:
    with TestClient(app) as client:
        r = client.get(
            f"/llm/configs/{FFAI_AIDEN_TIER_1}/tool_history",
            headers=_hdr(KLEAR_OWNER),
        )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error"] == "llm_config_not_found"


@iwo3_db
def test_get_tool_history_403_when_role_missing_audit_permission() -> None:
    asyncio.run(_drop_viewer_audit_perm())
    try:
        with TestClient(app) as client:
            r = client.get(
                f"/llm/configs/{MARK_TIER_2_LLM_CONFIG_ID}/tool_history",
                headers=_hdr(KLEAR_VIEWER),
            )
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["permission"] == "audit_log:read"
    finally:
        asyncio.run(_restore_viewer_audit_perm())
