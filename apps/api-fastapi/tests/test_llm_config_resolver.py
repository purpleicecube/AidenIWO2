"""Loop 9 Phase 9.3 — effective LLM config resolution.

Exercises the (client_id, agent_role) → tenant default fallback against
the seeded llm_configs.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

from llm.config_resolver import resolve_llm_config


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])


@iwo3_db
def test_direct_role_resolves() -> None:
    async def run() -> None:
        conn = await _connect()
        try:
            cfg = await resolve_llm_config(
                conn, client_id=KLEAR_CLIENT, agent_role="mark_tier_2"
            )
            assert cfg is not None
            assert cfg.requested_role == "mark_tier_2"
            assert cfg.resolved_role == "mark_tier_2"
            assert cfg.source == "role"
            assert cfg.provider in {"groq", "openrouter"}
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_unknown_role_falls_back_to_tenant_default() -> None:
    async def run() -> None:
        conn = await _connect()
        try:
            cfg = await resolve_llm_config(
                conn,
                client_id=KLEAR_CLIENT,
                agent_role="never_seeded_role",
            )
            assert cfg is not None
            assert cfg.requested_role == "never_seeded_role"
            assert cfg.resolved_role == "aiden_tier_1"
            assert cfg.source == "tenant_default"
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_tenant_default_role_no_fallback_when_missing() -> None:
    # If a tenant has no aiden_tier_1 row at all, resolution returns None.
    # Use a scratch client that won't have any seed.
    async def run() -> None:
        scratch = str(uuid.uuid4())
        conn = await _connect()
        try:
            await conn.execute(
                """
                INSERT INTO clients
                  (id, designation, display_name, deployment_mode, status)
                VALUES ($1, 'IWO | resolver-scratch', 'resolver-scratch',
                        'dedicated_single_client', 'active')
                """,
                scratch,
            )
            try:
                cfg = await resolve_llm_config(
                    conn, client_id=scratch, agent_role="mark_tier_2"
                )
                assert cfg is None
                cfg2 = await resolve_llm_config(
                    conn, client_id=scratch, agent_role="aiden_tier_1"
                )
                assert cfg2 is None
            finally:
                await conn.execute(
                    "DELETE FROM clients WHERE id = $1", scratch
                )
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_disabled_row_is_skipped() -> None:
    async def run() -> None:
        conn = await _connect()
        try:
            # Toggle Mark off, expect fallback to aiden_tier_1.
            await conn.execute(
                """
                UPDATE llm_configs SET enabled = false
                 WHERE client_id = $1 AND agent_role = 'mark_tier_2'
                """,
                KLEAR_CLIENT,
            )
            try:
                cfg = await resolve_llm_config(
                    conn,
                    client_id=KLEAR_CLIENT,
                    agent_role="mark_tier_2",
                )
                assert cfg is not None
                assert cfg.resolved_role == "aiden_tier_1"
                assert cfg.source == "tenant_default"
            finally:
                await conn.execute(
                    """
                    UPDATE llm_configs SET enabled = true
                     WHERE client_id = $1 AND agent_role = 'mark_tier_2'
                    """,
                    KLEAR_CLIENT,
                )
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_klear_does_not_see_ffai_rows() -> None:
    async def run() -> None:
        conn = await _connect()
        try:
            # Klear Mark must resolve to a row with client_id == KLEAR_CLIENT.
            cfg = await resolve_llm_config(
                conn, client_id=KLEAR_CLIENT, agent_role="mark_tier_2"
            )
            assert cfg is not None
            assert cfg.client_id == KLEAR_CLIENT
        finally:
            await conn.close()

    asyncio.run(run())
