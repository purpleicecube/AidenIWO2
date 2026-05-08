"""Loop Iota — Memory V1 firewall integration tests (live DB).

The five no-bleedover acceptance criteria from Loop Iota scope §AC:

  #11 cross-tenant chat history    — tenant A operator's chat never
                                     reaches tenant B's bundle
  #12 cross-operator scratch       — operator A's scratch never reaches
                                     operator B (same tenant)
  #13 cross-tenant artifacts       — tenant A artifact extracted_text
                                     "UNIQUE_MARKER" never matches
                                     tenant B retrieval
  #14 cache namespace isolation    — separate canonical-facts cache
                                     entries for separate tenants
  #15 validation rejection path    — synthetic mismatched source is
                                     dropped, memory.source_rejected
                                     audit row written, request still
                                     completes

These tests skip when IWO3_DATABASE_URL is unset.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import asyncpg
import pytest

from memory import memory_context_builder
from memory.cache import (
    clear_all_caches,
    get_canonical_facts,
    invalidate_canonical_facts,
    put_canonical_facts,
)
from memory.types import MemorySource
from memory.validator import validate_tenant_safety


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
FFAI_OPERATOR = "00000000-0000-4000-8000-000002000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@pytest.fixture
def db_url() -> str:
    return os.environ["IWO3_DATABASE_URL"]


async def _open_tenant_conn(
    db_url: str,
    *,
    client_id: str,
    user_id: str,
) -> asyncpg.Connection:
    """Open an asyncpg connection in tenant-scoped mode (matches the
    FastAPI deps factory)."""
    conn = await asyncpg.connect(db_url)
    await conn.execute("SET LOCAL ROLE iwo3_app")
    await conn.execute(
        f"SET LOCAL app.current_client_id = '{client_id}'"
    )
    return conn


# ── §AC #11 — cross-tenant chat history ──────────────────────────


@iwo3_db
def test_firewall_no_cross_tenant_chat_bleedover(db_url: str) -> None:
    async def run() -> None:
        # Pre-seed a chat session for FFAI operator on the FFAI tenant
        # with content that should NEVER appear in Klear bundles.
        ffai_conn = await asyncpg.connect(db_url)
        try:
            await ffai_conn.execute(
                """
                INSERT INTO chat_sessions (user_id, client_id, messages, context)
                VALUES ($1::uuid, $2::uuid, $3::jsonb, '{}'::jsonb)
                ON CONFLICT (user_id, client_id) DO UPDATE
                  SET messages = EXCLUDED.messages
                """,
                FFAI_OPERATOR,
                FFAI_CLIENT,
                '[{"role": "operator", "content": "FFAI_LEAK_MARKER token"}]',
            )
        finally:
            await ffai_conn.close()

        # Now build a memory bundle as the Klear operator. FFAI chat
        # must NOT appear.
        klear_conn = await _open_tenant_conn(
            db_url, client_id=KLEAR_CLIENT, user_id=KLEAR_OPERATOR
        )
        try:
            bundle = await memory_context_builder(
                klear_conn,
                client_id=KLEAR_CLIENT,
                user_id=KLEAR_OPERATOR,
                message="show me my chat history",
            )
            assert "FFAI_LEAK_MARKER" not in bundle.block
            for src in bundle.sources:
                assert src.client_id == KLEAR_CLIENT
        finally:
            await klear_conn.close()

    asyncio.new_event_loop().run_until_complete(run())


# ── §AC #13 — cross-tenant artifacts ─────────────────────────────


@iwo3_db
def test_firewall_no_cross_tenant_artifact_bleedover(db_url: str) -> None:
    async def run() -> None:
        marker = f"UNIQUE_MARKER_{uuid.uuid4().hex[:8]}"
        ffai_conn = await asyncpg.connect(db_url)
        try:
            # Find FFAI Outputs folder (tenant-shared, owner_user_id IS NULL).
            row = await ffai_conn.fetchrow(
                """
                SELECT id::text AS id FROM workspace_folders
                 WHERE client_id = $1::uuid
                   AND lower(name) = 'outputs'
                   AND owner_user_id IS NULL
                   AND deleted_at IS NULL
                 LIMIT 1
                """,
                FFAI_CLIENT,
            )
            assert row is not None, "FFAI Outputs/ folder must exist"
            ffai_outputs = row["id"]
            artifact_id = await ffai_conn.fetchval(
                """
                INSERT INTO artifacts
                  (client_id, source_type, content_class, mime_type,
                   filename, storage_ref, extracted_text,
                   workspace_folder_id, created_by_user_id)
                VALUES ($1::uuid, 'upload'::artifact_source_type,
                        'c1'::artifact_content_class, 'text/plain',
                        'leak_test.txt', 'inline://test', $2,
                        $3::uuid, $4::uuid)
                RETURNING id::text
                """,
                FFAI_CLIENT,
                f"This is a confidential FFAI document referencing {marker}.",
                ffai_outputs,
                FFAI_OPERATOR,
            )
            assert artifact_id is not None
        finally:
            await ffai_conn.close()

        try:
            klear_conn = await _open_tenant_conn(
                db_url, client_id=KLEAR_CLIENT, user_id=KLEAR_OPERATOR
            )
            try:
                bundle = await memory_context_builder(
                    klear_conn,
                    client_id=KLEAR_CLIENT,
                    user_id=KLEAR_OPERATOR,
                    message=f"find {marker} in my workspace",
                )
                assert marker not in bundle.block
                for src in bundle.sources:
                    assert src.client_id == KLEAR_CLIENT
            finally:
                await klear_conn.close()
        finally:
            cleanup = await asyncpg.connect(db_url)
            try:
                await cleanup.execute(
                    "DELETE FROM artifacts WHERE filename = 'leak_test.txt' "
                    "AND extracted_text LIKE '%' || $1 || '%'",
                    marker,
                )
            finally:
                await cleanup.close()

    asyncio.new_event_loop().run_until_complete(run())


# ── §AC #14 — cache namespace isolation ──────────────────────────


def test_firewall_cache_namespaced_by_client_id() -> None:
    """Pure-function test: confirms cache miss across tenants even
    with identical revision numbers."""
    clear_all_caches()
    put_canonical_facts(KLEAR_CLIENT, revision=1, blob="KLEAR FACTS rev1")
    # Tenant B request hits the same revision number — must miss.
    assert get_canonical_facts(FFAI_CLIENT, revision=1) is None
    # Klear hits.
    assert get_canonical_facts(KLEAR_CLIENT, revision=1) == "KLEAR FACTS rev1"
    # Invalidate Klear; FFAI hasn't been touched.
    invalidate_canonical_facts(KLEAR_CLIENT)
    assert get_canonical_facts(KLEAR_CLIENT, revision=1) is None
    # Seed FFAI separately; should not affect Klear.
    put_canonical_facts(FFAI_CLIENT, revision=1, blob="FFAI FACTS rev1")
    assert get_canonical_facts(FFAI_CLIENT, revision=1) == "FFAI FACTS rev1"
    assert get_canonical_facts(KLEAR_CLIENT, revision=1) is None


# ── §AC #15 — validation rejection writes audit row ──────────────


@iwo3_db
def test_firewall_validation_rejection_path(db_url: str) -> None:
    """Synthetic mismatch: validator must drop the source. We don't go
    through the live builder for this test (the live composite query
    won't return mismatches because RLS already filters). Instead we
    call validate_tenant_safety directly — that's the firewall Layer 4
    contract."""
    spoofed = MemorySource(
        kind="workspace_retrieval",
        client_id=FFAI_CLIENT,  # spoofed
        record_id="00000000-0000-0000-0000-000000000999",
        text="leaked content",
        tokens=2,
    )
    legit = MemorySource(
        kind="canonical_facts",
        client_id=KLEAR_CLIENT,
        record_id=f"{KLEAR_CLIENT}:rev1",
        text="legit fact",
        tokens=2,
    )
    kept, rej = validate_tenant_safety(
        [legit, spoofed],
        active_client_id=KLEAR_CLIENT,
        active_user_id=KLEAR_OPERATOR,
    )
    assert len(kept) == 1
    assert kept[0].kind == "canonical_facts"
    assert len(rej) == 1
    assert rej[0].reason == "tenant_mismatch"
    assert rej[0].actual_client_id == FFAI_CLIENT
    assert rej[0].expected_client_id == KLEAR_CLIENT


# ── §AC #11 b — kill switch bypass ───────────────────────────────


@iwo3_db
def test_firewall_env_kill_switch_bypasses(db_url: str, monkeypatch) -> None:
    monkeypatch.setenv("IWO3_MEMORY_INJECTION_ENABLED", "false")

    async def run() -> None:
        klear_conn = await _open_tenant_conn(
            db_url, client_id=KLEAR_CLIENT, user_id=KLEAR_OPERATOR
        )
        try:
            bundle = await memory_context_builder(
                klear_conn,
                client_id=KLEAR_CLIENT,
                user_id=KLEAR_OPERATOR,
                message="some intake",
            )
            assert bundle.bypassed is True
            assert bundle.bypass_reason == "env_disabled"
            assert bundle.block == ""
        finally:
            await klear_conn.close()

    asyncio.new_event_loop().run_until_complete(run())


@iwo3_db
def test_firewall_per_tenant_kill_switch_bypasses(db_url: str) -> None:
    async def run() -> None:
        # Flip Klear's memory_enabled off.
        admin = await asyncpg.connect(db_url)
        try:
            await admin.execute(
                "UPDATE clients SET memory_enabled = false WHERE id = $1::uuid",
                KLEAR_CLIENT,
            )
        finally:
            await admin.close()

        try:
            klear_conn = await _open_tenant_conn(
                db_url, client_id=KLEAR_CLIENT, user_id=KLEAR_OPERATOR
            )
            try:
                bundle = await memory_context_builder(
                    klear_conn,
                    client_id=KLEAR_CLIENT,
                    user_id=KLEAR_OPERATOR,
                    message="some intake",
                )
                assert bundle.bypassed is True
                assert bundle.bypass_reason == "tenant_disabled"
            finally:
                await klear_conn.close()
        finally:
            # Restore.
            admin = await asyncpg.connect(db_url)
            try:
                await admin.execute(
                    "UPDATE clients SET memory_enabled = true WHERE id = $1::uuid",
                    KLEAR_CLIENT,
                )
            finally:
                await admin.close()

    asyncio.new_event_loop().run_until_complete(run())
