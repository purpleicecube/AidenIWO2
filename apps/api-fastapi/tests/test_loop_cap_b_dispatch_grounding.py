"""Loop CAP-B Φ.3 — dispatch_grounding integration tests (live DB).

Coverage for:
  - prefetch_dispatch_grounding returns a `client_grounding`
    MemorySource for tenants with a meaningful brand profile (Klear).
  - Returns None for tenants with only a skeleton brand profile (FF).
  - Always emits exactly one `memory.applied` row with
    `surface="dispatch_prefetch"` regardless of whether grounding
    was found (zero `sources_used` for skeleton tenants).
  - The returned source carries kind=client_grounding, client_id
    matches the tenant, owner_user_id is None (tenant-shared).
  - Memory wrapper accepts prefetch_sources and the assembled bundle
    includes the grounding source at SOURCE_PRIORITY slot 0 with the
    rendered block opening with the `## CLIENT BRAND PROFILE` header.
  - Firewall preserves: cross-tenant grounding never bleeds (Klear
    grounding stays in Klear bundle, FFAI bundle does not see it).

Skips when IWO3_DATABASE_URL is unset.
"""

from __future__ import annotations

import json
import os
import uuid

import asyncpg
import pytest

from memory.cache import clear_all_caches
from memory.dispatch_grounding import prefetch_dispatch_grounding
from memory.types import SOURCE_PRIORITY
from memory.wrappers import memory_context_builder_for_subagent


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
    db_url: str, *, client_id: str
) -> asyncpg.Connection:
    conn = await asyncpg.connect(db_url)
    await conn.execute("SET LOCAL ROLE iwo3_app")
    await conn.execute(
        f"SET LOCAL app.current_client_id = '{client_id}'"
    )
    return conn


async def _count_dispatch_prefetch_audit_rows(
    db_url: str, *, client_id: str, since
) -> int:
    """Count `memory.applied` rows with `surface=dispatch_prefetch` for
    a tenant since the given datetime. Uses superuser conn to bypass
    RLS for the count assertion."""
    raw = await asyncpg.connect(db_url)
    try:
        row = await raw.fetchrow(
            """
            SELECT count(*)::int AS n
            FROM action_audit_log
            WHERE client_id = $1::uuid
              AND action = 'memory.applied'
              AND created_at >= $2
              AND metadata @> jsonb_build_object('surface', 'dispatch_prefetch')
            """,
            client_id,
            since,
        )
        return int(row["n"]) if row else 0
    finally:
        await raw.close()


@iwo3_db
def test_klear_grounding_returns_client_grounding_source(db_url: str) -> None:
    """Klear has a full brand profile — prefetch returns a meaningful
    client_grounding MemorySource."""

    async def run() -> None:
        clear_all_caches()
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            source = await prefetch_dispatch_grounding(
                conn,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert source is not None, "Klear should yield grounding"
            assert source.kind == "client_grounding"
            assert source.client_id == KLEAR_CLIENT
            assert source.owner_user_id is None  # tenant-shared
            assert source.tokens > 0
            # Content shape sanity — Klear seed includes palette + voice + ICP
            assert "Palette" in source.text or "palette" in source.text
            assert "ICP" in source.text or "Klear" in source.text
            assert source.metadata.get("requires_brand_qa") is True
        finally:
            await conn.close()

    import asyncio
    asyncio.run(run())


@iwo3_db
def test_ffai_skeleton_returns_none_grounding(db_url: str) -> None:
    """FFAI brand profile is a skeleton (only template_handles +
    brand_terms; no palette / fonts / voice / ICP). Skeleton-row gate
    in `_has_meaningful_grounding` returns None."""

    async def run() -> None:
        clear_all_caches()
        conn = await _open_tenant_conn(db_url, client_id=FFAI_CLIENT)
        try:
            source = await prefetch_dispatch_grounding(
                conn,
                client_id=FFAI_CLIENT,
            )
            # FFAI seed has only brand_terms + template_handles (no
            # palette, fonts, voice, ICP). Single-line text → gate
            # returns None.
            assert source is None
        finally:
            await conn.close()

    import asyncio
    asyncio.run(run())


@iwo3_db
def test_audit_row_emitted_with_dispatch_prefetch_surface(db_url: str) -> None:
    """Every prefetch call emits exactly one `memory.applied` row with
    `surface=dispatch_prefetch` regardless of whether grounding was
    found. AC-5 acceptance check."""

    async def run() -> None:
        clear_all_caches()
        # Pin a window for the count assertion. Use server now() to
        # avoid clock skew between test host and Postgres.
        raw = await asyncpg.connect(db_url)
        try:
            since = await raw.fetchval("SELECT now()")
        finally:
            await raw.close()

        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            source = await prefetch_dispatch_grounding(
                conn,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert source is not None
        finally:
            await conn.close()

        n = await _count_dispatch_prefetch_audit_rows(
            db_url, client_id=KLEAR_CLIENT, since=since
        )
        assert n == 1, f"expected exactly 1 dispatch_prefetch audit row; got {n}"

    import asyncio
    asyncio.run(run())


@iwo3_db
def test_audit_emitted_even_when_skeleton_grounding(db_url: str) -> None:
    """FFAI skeleton produces no source but the audit row still fires
    (with empty sources_used). Operator should be able to confirm via
    audit that prefetch ran for every dispatch — AC-5."""

    async def run() -> None:
        clear_all_caches()
        raw = await asyncpg.connect(db_url)
        try:
            since = await raw.fetchval("SELECT now()")
        finally:
            await raw.close()

        conn = await _open_tenant_conn(db_url, client_id=FFAI_CLIENT)
        try:
            source = await prefetch_dispatch_grounding(
                conn,
                client_id=FFAI_CLIENT,
            )
            assert source is None
        finally:
            await conn.close()

        n = await _count_dispatch_prefetch_audit_rows(
            db_url, client_id=FFAI_CLIENT, since=since
        )
        assert n == 1, "audit row must fire even when grounding empty"

    import asyncio
    asyncio.run(run())


@iwo3_db
def test_grounding_slots_at_source_priority_zero(db_url: str) -> None:
    """`client_grounding` is at SOURCE_PRIORITY slot 0, ABOVE
    canonical_facts (1) and all retrieval kinds. Lock check."""
    assert SOURCE_PRIORITY["client_grounding"] == 0
    assert SOURCE_PRIORITY["canonical_facts"] == 1
    # All other kinds rank below.
    for kind, prio in SOURCE_PRIORITY.items():
        if kind == "client_grounding":
            continue
        assert prio > SOURCE_PRIORITY["client_grounding"], (
            f"{kind} priority {prio} must be > client_grounding (0)"
        )


@iwo3_db
def test_subagent_wrapper_includes_grounding_in_bundle(db_url: str) -> None:
    """Tier-2 wrapper accepts prefetch_sources and the assembled
    bundle includes client_grounding as the first source.
    The rendered block opens with the `## CLIENT BRAND PROFILE` header.
    """

    async def run() -> None:
        clear_all_caches()
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            grounding = await prefetch_dispatch_grounding(
                conn,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert grounding is not None

            # Use a synthetic WO id (the wrapper falls back to the
            # unknown-operator sentinel since the wo doesn't exist;
            # that's fine — we're testing the prefetch passthrough,
            # not the WO lookup).
            bundle = await memory_context_builder_for_subagent(
                conn,
                client_id=KLEAR_CLIENT,
                work_order_id=str(uuid.uuid4()),
                sub_agent_role="tom_tier_2",
                intake_text="Klear.ai Intro 5 slides about supporting US cities",
                actor_user_id=KLEAR_OPERATOR,
                prefetch_sources=[grounding],
            )
        finally:
            await conn.close()

        assert not bundle.bypassed
        assert bundle.sources, "bundle must carry sources"
        assert bundle.sources[0].kind == "client_grounding"
        assert "## CLIENT BRAND PROFILE" in bundle.block
        # Slot 0 means it appears BEFORE any canonical_facts header
        if "## CANONICAL FACTS" in bundle.block:
            assert bundle.block.index("## CLIENT BRAND PROFILE") < bundle.block.index(
                "## CANONICAL FACTS"
            )

    import asyncio
    asyncio.run(run())


@iwo3_db
def test_klear_grounding_does_not_bleed_into_ffai_bundle(db_url: str) -> None:
    """Cross-tenant firewall: a Klear grounding source CANNOT be
    injected into an FFAI bundle. Layer 4 validator (the assembly-time
    tenant-safety check) rejects mismatched client_id sources before
    they reach the rendered block.

    Tested at the validator level (not the full wrapper) so this
    test does NOT emit a `memory.source_rejected` audit row — the
    Loop Kappa CI cardinality gate (M-009 P0 watchlist) requires
    zero rejection rows after the full pytest pass. The validator
    is a pure function; running it directly proves the firewall
    catches the cross-tenant case without polluting the audit log.
    """
    from memory.validator import validate_tenant_safety

    async def run() -> None:
        clear_all_caches()
        # Build a Klear grounding source via the prefetch helper.
        klear_conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            klear_grounding = await prefetch_dispatch_grounding(
                klear_conn,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert klear_grounding is not None
            assert klear_grounding.client_id == KLEAR_CLIENT
        finally:
            await klear_conn.close()

        # Run the Layer 4 validator against an FFAI active context.
        # The Klear-tagged grounding source MUST be rejected.
        validated, rejections = validate_tenant_safety(
            [klear_grounding],
            active_client_id=FFAI_CLIENT,
            active_user_id=FFAI_OPERATOR,
        )
        assert len(validated) == 0, "Klear grounding survived FFAI validation"
        assert len(rejections) == 1, "expected exactly 1 rejection"
        rej = rejections[0]
        assert rej.kind == "client_grounding"
        assert rej.expected_client_id == FFAI_CLIENT
        assert rej.actual_client_id == KLEAR_CLIENT

    import asyncio
    asyncio.run(run())
