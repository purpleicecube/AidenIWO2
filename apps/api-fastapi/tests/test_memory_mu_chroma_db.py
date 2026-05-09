"""Loop Mu — Memory V3 Chroma + DB integration tests.

Coverage for:
  - Index → search round-trip on a tenant collection
  - Cross-tenant isolation: Klear vector cannot reach FFAI search
  - End-to-end: indexed artifact reaches `memory_context_builder.bundle.block`
    via `## SEMANTIC GROUNDING` section
  - Cleanup: tenant collection deletion removes all chunks

Skips when chromadb is not installed OR `IWO3_DATABASE_URL` is unset.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path

import asyncpg
import pytest


# Skip the entire module if chromadb is not available.
chromadb = pytest.importorskip("chromadb")  # noqa: F841

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)

KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


@pytest.fixture
def db_url() -> str:
    return os.environ["IWO3_DATABASE_URL"]


@pytest.fixture(autouse=True)
def _clean_chroma_for_test_tenants():
    """Reset the Chroma collections for the seeded test tenants
    before each test so previous-test residue doesn't pollute."""
    from memory.vector_store import delete_tenant_collection

    delete_tenant_collection(KLEAR_CLIENT)
    delete_tenant_collection(FFAI_CLIENT)
    yield
    delete_tenant_collection(KLEAR_CLIENT)
    delete_tenant_collection(FFAI_CLIENT)


# ── Indexing + search round-trip ─────────────────────────────────


def test_index_then_search_returns_inserted_chunk() -> None:
    from memory.vector_store import (
        index_artifact_for_tenant,
        semantic_search_for_tenant,
    )

    artifact_id = str(uuid.uuid4())
    text = (
        "Klear pricing for the enterprise tier is seven thousand dollars "
        "per month. The standard tier is three thousand. Implementation "
        "fees are billed separately and include a one-time setup."
    )
    n = index_artifact_for_tenant(
        client_id=KLEAR_CLIENT,
        artifact_id=artifact_id,
        filename="pricing_brief.md",
        text=text,
    )
    assert n >= 1

    hits = semantic_search_for_tenant(
        client_id=KLEAR_CLIENT,
        query="how much does the enterprise plan cost",
        top_k=3,
    )
    assert len(hits) >= 1
    top = hits[0]
    assert top["artifact_id"] == artifact_id
    assert top["filename"] == "pricing_brief.md"
    assert top["score"] > 0.0  # cosine similarity in [0, 1]


# ── Cross-tenant isolation (FIREWALL) ────────────────────────────


def test_cross_tenant_index_isolation() -> None:
    """Indexing into Klear does NOT make the chunk reachable from FFAI."""
    from memory.vector_store import (
        index_artifact_for_tenant,
        semantic_search_for_tenant,
    )

    klear_artifact = str(uuid.uuid4())
    secret_marker = f"KLEAR_VECTOR_SECRET_{uuid.uuid4().hex[:8]}"
    index_artifact_for_tenant(
        client_id=KLEAR_CLIENT,
        artifact_id=klear_artifact,
        filename="klear_secret.md",
        text=f"This document contains the marker {secret_marker} as well as "
             f"some other Klear-specific content.",
    )

    # FFAI search — should NOT reach Klear's chunk.
    ffai_hits = semantic_search_for_tenant(
        client_id=FFAI_CLIENT,
        query=secret_marker,
        top_k=10,
    )
    assert all(
        h["artifact_id"] != klear_artifact for h in ffai_hits
    ), f"FIREWALL VIOLATION: FFAI search returned Klear artifact {klear_artifact}"

    # Klear search — DOES reach the chunk.
    klear_hits = semantic_search_for_tenant(
        client_id=KLEAR_CLIENT,
        query=secret_marker,
        top_k=3,
    )
    assert any(
        h["artifact_id"] == klear_artifact for h in klear_hits
    )


# ── End-to-end via memory_context_builder ────────────────────────


@iwo3_db
def test_memory_context_builder_surfaces_semantic_section(db_url: str) -> None:
    async def run() -> None:
        from memory import memory_context_builder
        from memory.cache import clear_all_caches
        from memory.vector_store import index_artifact_for_tenant

        # Index a chunk under Klear.
        marker = f"MU_E2E_{uuid.uuid4().hex[:8]}"
        index_artifact_for_tenant(
            client_id=KLEAR_CLIENT,
            artifact_id=str(uuid.uuid4()),
            filename="mu_e2e.md",
            text=(
                f"This is the unique mu-loop end-to-end test marker {marker}. "
                f"It describes a hypothetical fuzzy semantic match scenario "
                f"that the deterministic tsquery would not surface because "
                f"the operator query uses different vocabulary."
            ),
        )

        clear_all_caches()
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute("SET LOCAL ROLE iwo3_app")
            await conn.execute(
                f"SET LOCAL app.current_client_id = '{KLEAR_CLIENT}'"
            )
            bundle = await memory_context_builder(
                conn,
                client_id=KLEAR_CLIENT,
                user_id=KLEAR_OPERATOR,
                # Use a query that wouldn't trigger tsquery (no overlap
                # with the indexed text) so the only signal is semantic.
                message=(
                    "tell me about the fuzzy text retrieval scenario "
                    "involving end-to-end testing markers"
                ),
            )
        finally:
            await conn.close()

        assert "## SEMANTIC GROUNDING" in bundle.block, (
            f"expected semantic section in bundle.block; got first 800: "
            f"{bundle.block[:800]}"
        )
        assert marker in bundle.block

    asyncio.run(run())


# ── Cleanup helper ───────────────────────────────────────────────


def test_delete_tenant_collection_clears_chunks() -> None:
    from memory.vector_store import (
        delete_tenant_collection,
        get_tenant_collection_or_none,
        index_artifact_for_tenant,
    )

    artifact_id = str(uuid.uuid4())
    index_artifact_for_tenant(
        client_id=KLEAR_CLIENT,
        artifact_id=artifact_id,
        filename="to_delete.md",
        text="delete me from the index in this test",
    )
    coll = get_tenant_collection_or_none(KLEAR_CLIENT)
    assert coll is not None

    ok = delete_tenant_collection(KLEAR_CLIENT)
    assert ok is True

    coll_after = get_tenant_collection_or_none(KLEAR_CLIENT)
    assert coll_after is None


# ── Env kill switch end-to-end ───────────────────────────────────


@iwo3_db
def test_env_kill_switch_skips_semantic(db_url: str, monkeypatch) -> None:
    """When IWO3_SEMANTIC_RETRIEVAL_ENABLED=false, semantic_hits is empty
    even when the tenant collection exists with relevant chunks."""
    monkeypatch.setenv("IWO3_SEMANTIC_RETRIEVAL_ENABLED", "false")

    async def run() -> None:
        from memory import memory_context_builder
        from memory.cache import clear_all_caches
        from memory.vector_store import index_artifact_for_tenant

        marker = f"MU_KILL_{uuid.uuid4().hex[:8]}"
        index_artifact_for_tenant(
            client_id=KLEAR_CLIENT,
            artifact_id=str(uuid.uuid4()),
            filename="kill_switch_test.md",
            text=f"some indexed content with marker {marker}",
        )

        clear_all_caches()
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute("SET LOCAL ROLE iwo3_app")
            await conn.execute(
                f"SET LOCAL app.current_client_id = '{KLEAR_CLIENT}'"
            )
            bundle = await memory_context_builder(
                conn,
                client_id=KLEAR_CLIENT,
                user_id=KLEAR_OPERATOR,
                message=f"asking about {marker}",
            )
        finally:
            await conn.close()

        assert marker not in bundle.block, (
            "env kill switch did NOT prevent semantic retrieval"
        )
        assert "## SEMANTIC GROUNDING" not in bundle.block

    asyncio.run(run())
