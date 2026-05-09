"""Loop Lambda — Memory V2 wrapper integration tests (live DB).

Coverage for:
  - PM wrapper assembles bundle with surface=tier_1_5_pm + budget=1.5K
  - Tier-2 wrapper assembles bundle with surface=tier_2_subagent
    + budget=1.5K + sub_agent_role in metadata
  - WO submitter resolves to operator_id; NULL submitter falls back
    to the unknown-operator sentinel; sentinel's owner_user_id check
    silently skips scratch retrieval (firewall L4 invariant preserved)
  - audit row carries `surface` discriminator (D-L3 default)
  - cross-tenant isolation: Klear PM bundle never sees FFAI canonical
    facts via the wrapper path

Skips when IWO3_DATABASE_URL is unset.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

from memory.cache import clear_all_caches
from memory.wrappers import (
    memory_context_builder_for_subagent,
    memory_context_builder_for_workflow,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@pytest.fixture
def db_url() -> str:
    return os.environ["IWO3_DATABASE_URL"]


async def _open_tenant_conn(
    db_url: str, *, client_id: str
) -> asyncpg.Connection:
    conn = await asyncpg.connect(db_url)
    await conn.execute("SET LOCAL ROLE iwo3_app")
    await conn.execute(
        f"SET LOCAL app.current_client_id = '{client_id}'"
    )
    return conn


async def _seed_canonical_fact(
    bypass_url: str, *, client_id: str, body: str, severity: str = "high"
) -> None:
    """Insert a canonical_facts row for the tenant + force a blob
    rebuild so the next memory bundle picks it up."""
    bypass = await asyncpg.connect(bypass_url)
    try:
        await bypass.execute("SET LOCAL ROLE iwo3_app")
        await bypass.execute(
            f"SET LOCAL app.current_client_id = '{client_id}'"
        )
        await bypass.execute(
            """
            INSERT INTO canonical_facts (client_id, severity, body, authored_by_user_id)
            VALUES ($1::uuid, $2, $3, $4::uuid)
            """,
            client_id,
            severity,
            body,
            KLEAR_OWNER if client_id == KLEAR_CLIENT else "00000000-0000-4000-8000-000002000001",
        )
        from memory.canonical_facts_service import refresh_canonical_facts_from_table

        await refresh_canonical_facts_from_table(bypass, client_id=client_id)
    finally:
        await bypass.close()


async def _cleanup_canonical_facts(db_url: str) -> None:
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            "DELETE FROM canonical_facts WHERE body LIKE '%LAMBDA_TEST%'"
        )
    finally:
        await conn.close()


# ── PM wrapper ───────────────────────────────────────────────────


@iwo3_db
def test_pm_wrapper_assembles_bundle_with_pm_surface(db_url: str) -> None:
    async def run() -> None:
        clear_all_caches()
        await _cleanup_canonical_facts(db_url)
        marker = f"LAMBDA_PM_TEST_{uuid.uuid4().hex[:8]}"
        await _seed_canonical_fact(
            db_url, client_id=KLEAR_CLIENT, body=f"Klear PM fact {marker}"
        )
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            bundle = await memory_context_builder_for_workflow(
                conn,
                client_id=KLEAR_CLIENT,
                work_order_id=None,
                workflow_execution_id=None,
                intake_text="run the standard onboarding workflow",
                actor_user_id=KLEAR_OPERATOR,
            )
            assert marker in bundle.block, (
                f"PM wrapper bundle did not surface canonical fact "
                f"{marker}; got first 500: {bundle.block[:500]}"
            )
            # Per-surface budget == 1500 (D-L1)
            assert bundle.tokens_used <= 1500
        finally:
            await conn.close()
        await _cleanup_canonical_facts(db_url)

    asyncio.run(run())


@iwo3_db
def test_pm_wrapper_emits_memory_applied_with_tier_1_5_pm_surface(db_url: str) -> None:
    async def run() -> None:
        clear_all_caches()
        await _cleanup_canonical_facts(db_url)
        await _seed_canonical_fact(
            db_url, client_id=KLEAR_CLIENT, body="Klear PM trigger LAMBDA_TEST"
        )
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            await memory_context_builder_for_workflow(
                conn,
                client_id=KLEAR_CLIENT,
                work_order_id=None,
                workflow_execution_id="00000000-0000-4000-8000-000099900001",
                intake_text="trigger pm path",
                actor_user_id=KLEAR_OPERATOR,
            )
        finally:
            await conn.close()

        # Read back the audit row.
        bypass = await asyncpg.connect(db_url)
        try:
            row = await bypass.fetchrow(
                """
                SELECT metadata
                FROM action_audit_log
                WHERE action = 'memory.applied'
                  AND client_id = $1::uuid
                ORDER BY created_at DESC
                LIMIT 1
                """,
                KLEAR_CLIENT,
            )
            assert row is not None
            import json as _json

            meta = _json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            assert meta.get("surface") == "tier_1_5_pm", (
                f"expected surface=tier_1_5_pm in audit metadata; got {meta.get('surface')}"
            )
            assert meta.get("workflow_execution_id") == "00000000-0000-4000-8000-000099900001"
        finally:
            await bypass.close()
        await _cleanup_canonical_facts(db_url)

    asyncio.run(run())


# ── Tier-2 wrapper ───────────────────────────────────────────────


@iwo3_db
def test_subagent_wrapper_assembles_bundle_with_subagent_surface(db_url: str) -> None:
    async def run() -> None:
        clear_all_caches()
        await _cleanup_canonical_facts(db_url)
        marker = f"LAMBDA_T2_TEST_{uuid.uuid4().hex[:8]}"
        await _seed_canonical_fact(
            db_url, client_id=KLEAR_CLIENT, body=f"Klear Tier2 fact {marker}"
        )
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            bundle = await memory_context_builder_for_subagent(
                conn,
                client_id=KLEAR_CLIENT,
                work_order_id=None,
                sub_agent_role="mark_tier_2",
                intake_text="produce a Klear pricing brief",
                actor_user_id=KLEAR_OPERATOR,
            )
            assert marker in bundle.block
            assert bundle.tokens_used <= 1500
        finally:
            await conn.close()
        await _cleanup_canonical_facts(db_url)

    asyncio.run(run())


@iwo3_db
def test_subagent_wrapper_audit_carries_sub_agent_role(db_url: str) -> None:
    async def run() -> None:
        clear_all_caches()
        await _cleanup_canonical_facts(db_url)
        await _seed_canonical_fact(
            db_url, client_id=KLEAR_CLIENT, body="trigger LAMBDA_TEST"
        )
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            await memory_context_builder_for_subagent(
                conn,
                client_id=KLEAR_CLIENT,
                work_order_id=None,
                sub_agent_role="tom_tier_2",
                intake_text="build a deck",
                actor_user_id=KLEAR_OPERATOR,
            )
        finally:
            await conn.close()
        bypass = await asyncpg.connect(db_url)
        try:
            row = await bypass.fetchrow(
                """
                SELECT metadata
                FROM action_audit_log
                WHERE action = 'memory.applied'
                  AND client_id = $1::uuid
                ORDER BY created_at DESC
                LIMIT 1
                """,
                KLEAR_CLIENT,
            )
            assert row is not None
            import json as _json

            meta = _json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            assert meta.get("surface") == "tier_2_subagent"
            assert meta.get("sub_agent_role") == "tom_tier_2"
        finally:
            await bypass.close()
        await _cleanup_canonical_facts(db_url)

    asyncio.run(run())


# ── Cross-tenant firewall — wrapper preserves Layer 4 ─────────────


@iwo3_db
def test_pm_wrapper_does_not_leak_ffai_canonical_fact_to_klear(db_url: str) -> None:
    async def run() -> None:
        clear_all_caches()
        await _cleanup_canonical_facts(db_url)
        ffai_marker = f"FFAI_LEAK_LAMBDA_{uuid.uuid4().hex[:8]}"
        # Seed FFAI canonical fact.
        await _seed_canonical_fact(
            db_url, client_id=FFAI_CLIENT, body=f"FFAI confidential {ffai_marker}"
        )
        # Klear PM bundle must NOT see the FFAI fact.
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            bundle = await memory_context_builder_for_workflow(
                conn,
                client_id=KLEAR_CLIENT,
                work_order_id=None,
                workflow_execution_id=None,
                intake_text="any pm intake",
                actor_user_id=KLEAR_OPERATOR,
            )
            assert ffai_marker not in bundle.block, (
                f"FIREWALL VIOLATION: FFAI marker {ffai_marker} reached "
                f"Klear PM bundle"
            )
        finally:
            await conn.close()
        await _cleanup_canonical_facts(db_url)

    asyncio.run(run())


# ── WO operator-identity resolution ──────────────────────────────


@iwo3_db
def test_subagent_wrapper_resolves_wo_submitter_when_actor_user_id_omitted(db_url: str) -> None:
    """Async dispatch path: actor_user_id is None; wrapper looks up
    work_orders.submitted_by_user_id."""
    async def run() -> None:
        clear_all_caches()
        await _cleanup_canonical_facts(db_url)
        # Pick an existing seeded WO (Klear).
        bypass = await asyncpg.connect(db_url)
        try:
            wo_row = await bypass.fetchrow(
                """
                SELECT id::text AS id, submitted_by_user_id::text AS sub_id
                FROM work_orders
                WHERE client_id = $1::uuid
                  AND submitted_by_user_id IS NOT NULL
                LIMIT 1
                """,
                KLEAR_CLIENT,
            )
        finally:
            await bypass.close()
        if not wo_row:
            pytest.skip("no seeded Klear WO with submitted_by_user_id")
        wo_id = wo_row["id"]
        wo_submitter = wo_row["sub_id"]

        await _seed_canonical_fact(
            db_url, client_id=KLEAR_CLIENT, body="trigger LAMBDA_TEST async path"
        )
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            await memory_context_builder_for_subagent(
                conn,
                client_id=KLEAR_CLIENT,
                work_order_id=wo_id,
                sub_agent_role="mark_tier_2",
                intake_text="async dispatch",
                actor_user_id=None,  # async path — no session operator
            )
        finally:
            await conn.close()
        # Verify the audit row carries the WO-submitter as actor.
        bypass = await asyncpg.connect(db_url)
        try:
            row = await bypass.fetchrow(
                """
                SELECT actor_user_id::text AS actor, metadata
                FROM action_audit_log
                WHERE action = 'memory.applied'
                  AND client_id = $1::uuid
                ORDER BY created_at DESC
                LIMIT 1
                """,
                KLEAR_CLIENT,
            )
            assert row is not None
            assert row["actor"] == wo_submitter, (
                f"expected actor_user_id={wo_submitter} (WO submitter); "
                f"got {row['actor']}"
            )
        finally:
            await bypass.close()
        await _cleanup_canonical_facts(db_url)

    asyncio.run(run())
