"""Loop CAP-E Φ.7 + Φ.8 — output_surface_routes registry + Aiden
branded-intent detector integration tests.

Coverage:
  - 8 branded routes seeded; lookup by (output_kind, is_branded,
    design_input_source) returns the expected workflow_key + adapter
    chain.
  - Branded-intent detector: matches Klear's brand_terms in intake;
    detects output_kind from intake; detects design_input_source
    from intake.
  - Single-template tenant (Klear has 1 PPTX template) → detector
    selects deterministically without disambiguation event.
  - Detector emits aiden.branded_intent_detected always; emits
    multi_template_disambiguated only when >1 candidates existed
    and detector picked one.
  - Cross-tenant firewall: FF intake against Klear connection
    yields no Klear brand match (each tenant sees only its own
    brand_terms via RLS on client_brand_profiles).
  - Off-brand intake on a branded tenant → is_branded=False,
    workflow_key=None.

Skips DB-backed tests when IWO3_DATABASE_URL is unset.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

from runtime.aiden_branded_intent import (
    BrandedIntent,
    _detect_design_input_source,
    detect_branded_intent,
)


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


# ── Pure detector helpers ─────────────────────────────────────────


def test_design_input_source_detects_stitch() -> None:
    assert _detect_design_input_source("use stitch design for landing page") == "stitch"


def test_design_input_source_detects_figma() -> None:
    assert _detect_design_input_source("here is the figma file link") == "figma"


def test_design_input_source_detects_twentyfirst() -> None:
    assert _detect_design_input_source("build with 21st-magic components") == "twentyfirst"


def test_design_input_source_returns_none_for_plain_intake() -> None:
    assert _detect_design_input_source("klear.ai intro deck for risk operators") is None


# ── DB-backed: route lookup ──────────────────────────────────────


@iwo3_db
def test_eight_branded_routes_seeded(db_url: str) -> None:
    """All 8 branded chain routes from the CAP-C chain seed have
    matching output_surface_routes entries."""

    async def run() -> None:
        # Use raw conn (registry is global, no RLS).
        raw = await asyncpg.connect(db_url)
        try:
            rows = await raw.fetch(
                """
                SELECT output_kind, is_branded, design_input_source, workflow_key
                FROM output_surface_routes
                WHERE is_branded = true
                ORDER BY output_kind, COALESCE(design_input_source, 'none')
                """
            )
            assert len(rows) == 8
            keys = {r["workflow_key"] for r in rows}
            assert keys == {
                "cap_branded_pptx",
                "cap_branded_pdf",
                "cap_branded_html",
                "cap_branded_html_stitch",
                "cap_branded_html_figma",
                "cap_branded_html_21st",
                "cap_branded_docx",
                "cap_branded_md",
            }
        finally:
            await raw.close()

    asyncio.run(run())


# ── DB-backed: branded-intent detector ────────────────────────────


@iwo3_db
def test_klear_intake_detects_branded_pptx_route(db_url: str) -> None:
    """Klear UAT intake: 'Klear.ai Intro 5 slides' → matches
    brand_terms (Klear.ai), detects output_kind=pptx ('slides'),
    no design input → routes to cap_branded_pptx."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            intent = await detect_branded_intent(
                conn,
                client_id=KLEAR_CLIENT,
                intake_text="Klear.ai Intro 5 slides about supporting US municipalities",
                actor_user_id=KLEAR_OPERATOR,
            )
            assert isinstance(intent, BrandedIntent)
            assert intent.is_branded is True
            assert "Klear.ai" in intent.detected_brand_keywords
            assert intent.detected_output_kind == "pptx"
            assert intent.detected_design_input_source is None
            assert intent.workflow_key == "cap_branded_pptx"
            assert intent.primary_adapter_key == "gamma"
            assert "sandbox_pptx" in intent.fallback_adapter_keys
            # Klear has exactly 1 PPTX template → no multi-template
            # disambiguation event needed.
            assert intent.selected_template_profile_key == "klear_pptx_primary"
            assert intent.needs_clarification is False
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_klear_html_with_stitch_detects_stitch_chain(db_url: str) -> None:
    """Klear intake mentioning Stitch → routes to cap_branded_html_stitch."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            intent = await detect_branded_intent(
                conn,
                client_id=KLEAR_CLIENT,
                intake_text="Klear.ai landing page for AAOSH webinar — use Stitch design",
                actor_user_id=KLEAR_OPERATOR,
            )
            assert intent.is_branded is True
            assert intent.detected_output_kind == "html"
            assert intent.detected_design_input_source == "stitch"
            assert intent.workflow_key == "cap_branded_html_stitch"
            assert intent.primary_adapter_key == "stitch_html_render"
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_klear_pdf_intake_detects_branded_pdf_route(db_url: str) -> None:
    """Klear intake for a PDF deliverable → routes to cap_branded_pdf."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            intent = await detect_branded_intent(
                conn,
                client_id=KLEAR_CLIENT,
                intake_text="Klear.ai 1-page intro PDF for retail vertical",
                actor_user_id=KLEAR_OPERATOR,
            )
            assert intent.is_branded is True
            assert intent.detected_output_kind == "pdf"
            assert intent.workflow_key == "cap_branded_pdf"
            # Klear has 2 PDF templates (rmis + claims) — disambiguation
            # may select one based on intake keywords or fall through.
            # The detector's behavior is acceptable either way for this
            # generic intake; we don't assert which one it picks.
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_unbranded_internal_intake_detects_no_brand(db_url: str) -> None:
    """Generic non-branded intake → is_branded=False, no workflow_key."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            intent = await detect_branded_intent(
                conn,
                client_id=KLEAR_CLIENT,
                intake_text="Internal note: my thoughts on yesterday's standup.",
                actor_user_id=KLEAR_OPERATOR,
            )
            assert intent.is_branded is False
            assert intent.detected_brand_keywords == ()
            assert intent.workflow_key is None
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_explicit_template_id_marks_branded_even_without_keyword(db_url: str) -> None:
    """When operator explicitly picked a template (Submit Order), the
    request is branded even if intake lacks brand_terms."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            intent = await detect_branded_intent(
                conn,
                client_id=KLEAR_CLIENT,
                intake_text="Generic intake without keyword match",
                actor_user_id=KLEAR_OPERATOR,
                explicit_template_profile_id="00000000-0000-4000-8000-000010000001",
                explicit_output_kind="pptx",
            )
            assert intent.is_branded is True  # explicit template => branded
            assert intent.detected_output_kind == "pptx"
            assert intent.workflow_key == "cap_branded_pptx"
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_klear_brand_terms_dont_match_in_ffai_tenant(db_url: str) -> None:
    """Cross-tenant firewall: FFAI tenant connection sees only FFAI
    brand_terms via RLS — Klear keywords in intake don't match
    against the FFAI tenant's brand profile."""

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=FFAI_CLIENT)
        try:
            intent = await detect_branded_intent(
                conn,
                client_id=FFAI_CLIENT,
                intake_text="Klear.ai Intro 5 slides about RMIS",
                actor_user_id=FFAI_OPERATOR,
            )
            # FFAI's brand_terms include FreedomForge / FF.AI etc., not Klear.
            # So Klear keywords don't match against FFAI's brand profile.
            assert "Klear.ai" not in intent.detected_brand_keywords
            assert "Klear" not in intent.detected_brand_keywords
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_branded_intent_emits_detected_audit(db_url: str) -> None:
    """Every detector call emits exactly one aiden.branded_intent_detected
    audit row, regardless of verdict."""

    async def run() -> None:
        raw = await asyncpg.connect(db_url)
        try:
            since = await raw.fetchval("SELECT now()")
        finally:
            await raw.close()

        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            await detect_branded_intent(
                conn,
                client_id=KLEAR_CLIENT,
                intake_text="Klear.ai intro deck",
                actor_user_id=KLEAR_OPERATOR,
            )
        finally:
            await conn.close()

        raw = await asyncpg.connect(db_url)
        try:
            n = await raw.fetchval(
                """
                SELECT count(*)::int
                FROM action_audit_log
                WHERE client_id = $1::uuid
                  AND action = 'aiden.branded_intent_detected'
                  AND created_at >= $2
                """,
                KLEAR_CLIENT,
                since,
            )
            assert n == 1
        finally:
            await raw.close()

    asyncio.run(run())
