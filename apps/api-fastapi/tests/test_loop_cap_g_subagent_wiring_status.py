"""Loop CAP-G CLOSEOUT Slice C — sub-agent wiring status surface tests.

Coverage:
  - `build_sub_agent_wiring_status` returns the expected per-role
    matrix shape with all required fields
  - Legacy seed labels (`mark`, `pm_alpha`, `agent_system`) are
    excluded from the `roles[]` list
  - Klear roles in branded chains (mark/tom/hank/sop_master/darla/paul
    plus aiden + pm) are correctly flagged `branded_chain_path=True`
  - Direct-routing roles (jamie/nyx/polaris) are flagged
    `direct_work_order_path=True` even without branded chain presence
  - Degraded surfaces correctly identified for roles whose chains
    primary-route through `adapter_unavailable` adapters
    (sandbox_pdf / sandbox_docx / figma_html_render /
    twentyfirst_html_render)
  - Aiden tool registry includes `sub_agent_wiring_status` with the
    expected handler
  - Cross-tenant: FFAI tenant sees its own roles only (separate
    audit-log rollup; same canonical role set)

Skips DB-backed tests when IWO3_DATABASE_URL is unset.
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest

from runtime.aiden_tools import TOOL_REGISTRY
from runtime.subagent_wiring import (
    _CANONICAL_ROLE_KEYS,
    _LEGACY_SEED_LABELS,
    build_sub_agent_wiring_status,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"


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


# ── Aiden tool registry ──────────────────────────────────────────


def test_aiden_tool_registry_includes_sub_agent_wiring_status() -> None:
    """The Aiden tool catalog must include `sub_agent_wiring_status`
    so Aiden can retrieve live wiring truth without hallucination."""
    assert "sub_agent_wiring_status" in TOOL_REGISTRY
    tool = TOOL_REGISTRY["sub_agent_wiring_status"]
    assert tool.name == "sub_agent_wiring_status"
    assert tool.handler is not None
    # Empty args schema — no operator-facing parameters.
    assert tool.args_schema.get("properties") == {}


# ── Matrix shape + role canonicalization ──────────────────────────


@iwo3_db
def test_matrix_returns_canonical_role_keys_only(db_url: str) -> None:
    """The matrix `roles[]` list must contain EXACTLY the canonical
    role keys — no legacy seed labels (`mark`, `pm_alpha`,
    `agent_system`) ever appear as their own row."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            status = await build_sub_agent_wiring_status(
                conn, client_id=KLEAR_CLIENT
            )
            role_keys = {r["role_key"] for r in status["roles"]}
            assert role_keys == set(_CANONICAL_ROLE_KEYS)
            # Legacy labels must NEVER appear
            for legacy in ("mark", "pm_alpha", "agent_system"):
                assert legacy not in role_keys, (
                    f"legacy seed label '{legacy}' must not appear in live matrix"
                )
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_matrix_per_role_has_required_fields(db_url: str) -> None:
    """Each role row must carry every spec-mandated field per the
    `IWO3_SUBAGENT_WIRING_MATRIX_AND_STATUS_SURFACE` deliverable."""
    required_fields = {
        "role_key",
        "display_name",
        "layer",
        "llm_enabled",
        "direct_work_order_path",
        "workflow_path",
        "branded_chain_path",
        "surfaces",
        "degraded",
        "degraded_reason",
        "last_invoked_at",
        "last_success_at",
        "last_failure_at",
    }

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            status = await build_sub_agent_wiring_status(
                conn, client_id=KLEAR_CLIENT
            )
            for r in status["roles"]:
                missing = required_fields - set(r.keys())
                assert not missing, f"role {r.get('role_key')} missing fields: {missing}"
        finally:
            await conn.close()

    asyncio.run(run())


# ── Branded chain presence ───────────────────────────────────────


@iwo3_db
def test_klear_branded_chain_roles_flagged_correctly(db_url: str) -> None:
    """The 6 Tier-2 roles seeded in CAP-C branded chains
    (mark/tom/hank/sop_master/darla/paul) must have
    `branded_chain_path=True`. PM is in chain instantiation but not
    in step rows; tier_1 Aiden routes to chains externally."""
    expected_branded = {
        "mark_tier_2",
        "tom_tier_2",
        "hank_tier_2",
        "sop_master_tier_2",
        "darla_tier_2",
        "paul_tier_2",
    }

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            status = await build_sub_agent_wiring_status(
                conn, client_id=KLEAR_CLIENT
            )
            by_key = {r["role_key"]: r for r in status["roles"]}
            for role in expected_branded:
                assert by_key[role]["branded_chain_path"] is True, (
                    f"{role} must be flagged branded_chain_path=True"
                )
            # Non-branded tier-2 roles
            for role in ("jamie_tier_2", "nyx_tier_2", "polaris_tier_2"):
                assert by_key[role]["branded_chain_path"] is False, (
                    f"{role} must NOT be flagged branded_chain_path"
                )
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_direct_routing_roles_include_all_tier_2(db_url: str) -> None:
    """All 9 Tier-2 roles (jamie / mark / nyx / polaris / darla /
    sop_master / tom / hank / paul) must be flagged
    `direct_work_order_path=True` — Aiden can route any of them on
    the `work_order_brief` path."""
    expected_direct = {
        "mark_tier_2", "tom_tier_2", "hank_tier_2", "sop_master_tier_2",
        "darla_tier_2", "paul_tier_2",
        "jamie_tier_2", "nyx_tier_2", "polaris_tier_2",
    }

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            status = await build_sub_agent_wiring_status(
                conn, client_id=KLEAR_CLIENT
            )
            by_key = {r["role_key"]: r for r in status["roles"]}
            for role in expected_direct:
                assert by_key[role]["direct_work_order_path"] is True, (
                    f"{role} must be flagged direct_work_order_path=True"
                )
        finally:
            await conn.close()

    asyncio.run(run())


# ── Degraded surfaces ────────────────────────────────────────────


@iwo3_db
def test_degraded_surfaces_marked_for_adapter_unavailable_chains(
    db_url: str,
) -> None:
    """Roles whose branded chains primary-route through
    `adapter_unavailable` adapters (sandbox_pdf, sandbox_docx,
    figma_html_render, twentyfirst_html_render) must be flagged
    `degraded=True` with a human-readable reason."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            status = await build_sub_agent_wiring_status(
                conn, client_id=KLEAR_CLIENT
            )
            by_key = {r["role_key"]: r for r in status["roles"]}
            # A role is degraded when its branded chain's PRIMARY
            # adapter is in _DEGRADED_ADAPTER_KEYS. Per CAP-E registry
            # seeds, the degraded primaries are:
            #   figma_html_render (html+figma chain primary)
            #   twentyfirst_html_render (html+21st chain primary)
            #   sandbox_docx (docx chain primary)
            # So:
            #   Paul (delivery, every chain) → degraded (3 surfaces)
            #   Hank (html render) → degraded (figma + 21st)
            #   SOP Master (docx/md render) → degraded (docx)
            # NOT degraded:
            #   Tom (pptx/pdf render) — primary is gamma (functional);
            #     sandbox_pptx/sandbox_pdf are only fallbacks
            #   Mark (content_brief), Darla (brand_qa) — not render roles
            assert by_key["paul_tier_2"]["degraded"] is True
            assert by_key["paul_tier_2"]["degraded_reason"]
            assert by_key["hank_tier_2"]["degraded"] is True
            assert by_key["sop_master_tier_2"]["degraded"] is True
            # Tom NOT degraded — Gamma is functional primary for both pptx + pdf
            assert by_key["tom_tier_2"]["degraded"] is False
            # Mark is the content_brief role; not a render role.
            assert by_key["mark_tier_2"]["degraded"] is False
            # Darla is the brand_qa role; not a render role.
            assert by_key["darla_tier_2"]["degraded"] is False
        finally:
            await conn.close()

    asyncio.run(run())


# ── Summary block ────────────────────────────────────────────────


@iwo3_db
def test_summary_counts_are_accurate(db_url: str) -> None:
    """The `summary` block must accurately reflect the counts in
    `roles[]`. Tier-2 branded chain count = 6 (per CAP-C seeded
    chains). Degraded count = 4 (paul + tom + hank + sop_master)."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            status = await build_sub_agent_wiring_status(
                conn, client_id=KLEAR_CLIENT
            )
            summary = status["summary"]
            assert summary["tier_2_branded_chain_roles"] == 6
            # 3 degraded: paul + hank + sop_master (Tom is not
            # degraded because PDF's primary is Gamma, not the
            # adapter_unavailable sandbox_pdf stub).
            assert summary["degraded_roles"] == 3
            assert set(summary["legacy_seed_labels_excluded"]) >= {
                "mark",
                "pm_alpha",
                "agent_system",
            }
        finally:
            await conn.close()

    asyncio.run(run())


# ── Cross-tenant isolation ───────────────────────────────────────


@iwo3_db
def test_ffai_tenant_sees_own_matrix(db_url: str) -> None:
    """FFAI tenant connection produces a separate matrix scoped to
    FFAI's tenant_id, with FFAI's own audit rollup. Same canonical
    role keys (the canonical set is global), but tenant_id differs
    + audit rollups differ."""

    async def run() -> None:
        conn_ffai = await _open_tenant_conn(db_url, client_id=FFAI_CLIENT)
        try:
            status = await build_sub_agent_wiring_status(
                conn_ffai, client_id=FFAI_CLIENT
            )
            assert status["tenant_id"] == FFAI_CLIENT
            role_keys = {r["role_key"] for r in status["roles"]}
            assert role_keys == set(_CANONICAL_ROLE_KEYS)
        finally:
            await conn_ffai.close()

    asyncio.run(run())


# ── Legacy seed exclusion lock ───────────────────────────────────


def test_legacy_seed_labels_constant_includes_mandated_labels() -> None:
    """The spec mandates excluding `mark`, `pm_alpha`, `agent_system`
    from the live matrix. Lock that the constant includes these."""
    for legacy in ("mark", "pm_alpha", "agent_system"):
        assert legacy in _LEGACY_SEED_LABELS
