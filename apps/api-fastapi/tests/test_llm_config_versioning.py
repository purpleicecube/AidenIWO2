"""Beta-2 phase 0.3 — versioning + tri-state PATCH + rollback tests.

Covers the universal-slice closure of CODEX 2026-05-01 findings:
  - Load — `GET /llm/configs/{id}/prompt` returns the actual body
  - Tri-state PATCH — set / clear / unchanged with explicit prompt_action
  - Versioning — every mutation snapshots a full row into llm_config_versions
  - Rollback — pick a prior version, write a new mutation that restores it

Tests run against the live `aiden_iwo3` DB so RLS + iwo3_app GRANTs
exercise too. Each test seeds + cleans up its own llm_config row.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

import asyncpg
import pytest
from fastapi.testclient import TestClient

KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict[str, str]:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


async def _seed_throwaway_config() -> str:
    """Insert a fresh tier-2 config row + matching backfill version 1.
    Returns the config id. Tests clean up after themselves."""
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        cfg_id = str(uuid.uuid4())
        role = f"phase03_test_{uuid.uuid4().hex[:8]}_tier_2"
        await conn.execute(
            """
            INSERT INTO llm_configs
              (id, client_id, agent_role, display_name, description,
               provider, model, base_url, credential_ref, system_prompt,
               options, enabled)
            VALUES ($1, $2, $3, 'Phase 0.3 test agent', 'unit-test seed',
                    'groq', 'openai/gpt-oss-120b', NULL,
                    'credential_ref:env:GROQ_API_KEY', 'initial prompt body',
                    NULL, true)
            """,
            cfg_id, KLEAR_CLIENT, role,
        )
        # Mirror what migration 0021 does for new rows: write version 1.
        await conn.execute(
            """
            INSERT INTO llm_config_versions
              (llm_config_id, client_id, version_number, agent_role, provider,
               model, base_url, credential_ref, system_prompt, options, enabled,
               notes, display_name, description, change_action, change_reason)
            VALUES ($1, $2, 1, $3, 'groq', 'openai/gpt-oss-120b', NULL,
                    'credential_ref:env:GROQ_API_KEY', 'initial prompt body',
                    NULL, true, NULL, 'Phase 0.3 test agent', 'unit-test seed',
                    'initial', 'pytest seed')
            """,
            cfg_id, KLEAR_CLIENT, role,
        )
        return cfg_id
    finally:
        await conn.close()


async def _drop_config(cfg_id: str) -> None:
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        # llm_config_versions has ON DELETE CASCADE.
        await conn.execute(
            "DELETE FROM llm_configs WHERE id = $1::uuid", cfg_id
        )
    finally:
        await conn.close()


# ────────── Load ──────────


@iwo3_db
def test_get_prompt_returns_actual_body() -> None:
    from main import app

    cfg_id = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            r = c.get(
                f"/llm/configs/{cfg_id}/prompt", headers=_hdr(KLEAR_OWNER)
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["system_prompt"] == "initial prompt body"
        assert body["has_system_prompt"] is True
    finally:
        asyncio.run(_drop_config(cfg_id))


@iwo3_db
def test_get_prompt_403_for_viewer() -> None:
    """Read is writer-gated (llm_config:write). Viewer must 403."""
    from main import app

    cfg_id = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            r = c.get(
                f"/llm/configs/{cfg_id}/prompt", headers=_hdr(KLEAR_VIEWER)
            )
        assert r.status_code == 403
    finally:
        asyncio.run(_drop_config(cfg_id))


# ────────── Tri-state PATCH ──────────


@iwo3_db
def test_patch_prompt_action_set_writes_version() -> None:
    from main import app

    cfg_id = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            r = c.patch(
                f"/llm/configs/{cfg_id}",
                headers=_hdr(KLEAR_OWNER),
                json={
                    "prompt_action": "set",
                    "system_prompt": "phase 0.3 set test prompt",
                    "change_reason": "pytest set",
                },
            )
            assert r.status_code == 200, r.text
            assert r.json()["config"]["has_system_prompt"] is True
            v = c.get(
                f"/llm/configs/{cfg_id}/versions",
                headers=_hdr(KLEAR_OWNER),
            ).json()["versions"]
        # version 1 (seed) + version 2 (this patch)
        assert [x["version_number"] for x in v] == [2, 1]
        assert v[0]["change_action"] == "update"
        assert v[0]["has_system_prompt"] is True
        assert "system_prompt" in (v[0].get("changed_fields") or [])
    finally:
        asyncio.run(_drop_config(cfg_id))


@iwo3_db
def test_patch_prompt_action_clear_drops_to_null() -> None:
    from main import app

    cfg_id = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            r = c.patch(
                f"/llm/configs/{cfg_id}",
                headers=_hdr(KLEAR_OWNER),
                json={"prompt_action": "clear", "change_reason": "pytest clear"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["config"]["has_system_prompt"] is False
            pr = c.get(
                f"/llm/configs/{cfg_id}/prompt", headers=_hdr(KLEAR_OWNER)
            ).json()
            assert pr["system_prompt"] is None
            assert pr["has_system_prompt"] is False
    finally:
        asyncio.run(_drop_config(cfg_id))


@iwo3_db
def test_patch_ambiguous_prompt_payload_rejected() -> None:
    """system_prompt without prompt_action — closes CODEX finding 2."""
    from main import app

    cfg_id = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            r = c.patch(
                f"/llm/configs/{cfg_id}",
                headers=_hdr(KLEAR_OWNER),
                json={"system_prompt": "blind overwrite attempt"},
            )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "ambiguous_prompt_payload"
    finally:
        asyncio.run(_drop_config(cfg_id))


@iwo3_db
def test_patch_set_with_empty_string_rejected() -> None:
    from main import app

    cfg_id = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            r = c.patch(
                f"/llm/configs/{cfg_id}",
                headers=_hdr(KLEAR_OWNER),
                json={"prompt_action": "set", "system_prompt": "  "},
            )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "prompt_action_conflict"
    finally:
        asyncio.run(_drop_config(cfg_id))


@iwo3_db
def test_patch_unchanged_with_value_rejected() -> None:
    from main import app

    cfg_id = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            r = c.patch(
                f"/llm/configs/{cfg_id}",
                headers=_hdr(KLEAR_OWNER),
                json={"prompt_action": "unchanged", "system_prompt": "ignored"},
            )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "prompt_action_conflict"
    finally:
        asyncio.run(_drop_config(cfg_id))


# ────────── Rollback ──────────


@iwo3_db
def test_rollback_writes_new_version_and_restores_state() -> None:
    """Edit, then rollback to v1. Result: v3 carries v1's snapshot,
    live row matches v1, change_action='rollback'."""
    from main import app

    cfg_id = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            # Mutation → v2
            c.patch(
                f"/llm/configs/{cfg_id}",
                headers=_hdr(KLEAR_OWNER),
                json={
                    "prompt_action": "set",
                    "system_prompt": "v2 prompt",
                    "change_reason": "v2",
                },
            )
            v_list = c.get(
                f"/llm/configs/{cfg_id}/versions",
                headers=_hdr(KLEAR_OWNER),
            ).json()["versions"]
            v1 = next(x for x in v_list if x["version_number"] == 1)

            # Rollback to v1
            r = c.post(
                f"/llm/configs/{cfg_id}/rollback",
                headers=_hdr(KLEAR_OWNER),
                json={"version_id": v1["id"], "change_reason": "rb to v1"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["config"]["has_system_prompt"] is True

            # Live prompt should match v1 ("initial prompt body")
            pr = c.get(
                f"/llm/configs/{cfg_id}/prompt", headers=_hdr(KLEAR_OWNER)
            ).json()
            assert pr["system_prompt"] == "initial prompt body"

            # v3 should exist with change_action=rollback
            v_list_after = c.get(
                f"/llm/configs/{cfg_id}/versions",
                headers=_hdr(KLEAR_OWNER),
            ).json()["versions"]
            v3 = next(x for x in v_list_after if x["version_number"] == 3)
            assert v3["change_action"] == "rollback"
    finally:
        asyncio.run(_drop_config(cfg_id))


@iwo3_db
def test_rollback_rejects_version_from_different_config() -> None:
    from main import app

    cfg_a = asyncio.run(_seed_throwaway_config())
    cfg_b = asyncio.run(_seed_throwaway_config())
    try:
        with TestClient(app) as c:
            v_b = c.get(
                f"/llm/configs/{cfg_b}/versions",
                headers=_hdr(KLEAR_OWNER),
            ).json()["versions"]
            r = c.post(
                f"/llm/configs/{cfg_a}/rollback",
                headers=_hdr(KLEAR_OWNER),
                json={"version_id": v_b[0]["id"]},
            )
        assert r.status_code == 400
        assert (
            r.json()["detail"]["error"]
            == "version_belongs_to_different_config"
        )
    finally:
        asyncio.run(_drop_config(cfg_a))
        asyncio.run(_drop_config(cfg_b))
