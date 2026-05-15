"""Loop CAP-D Φ.5 + Φ.6 — Paul + Darla helper unit + DB tests.

Coverage:
  - _parse_attestation: valid pass / needs_revision / block payloads
    parse correctly from envelope.metadata; off-contract payloads
    fail closed to `block`.
  - _parse_decision: valid primary_dispatch / fallback_dispatch /
    blocked payloads parse correctly; off-contract fail closed to
    `blocked`.
  - _load_brand_profile_text: Klear yields full profile text;
    skeleton tenant returns None when no profile content.
  - _load_brand_template_choices: returns ordered list of
    template_profile rows per `template_handles_json[output_kind]`.
  - Audit event names match the locked vocabulary in
    `LOOP_CAP_D_PHI5_AUDIT_EVENTS` and `LOOP_CAP_D_PHI6_AUDIT_EVENTS`.

Skips DB-backed tests when IWO3_DATABASE_URL is unset; parser tests
are pure-Python and always run.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import asyncpg
import pytest

from runtime.darla_qa import (
    BrandAttestation,
    _parse_attestation,
)
from runtime.paul_delivery import (
    PaulDecision,
    _parse_decision,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@dataclass(frozen=True)
class FakeEnvelope:
    """Stand-in for Tier2OutputEnvelope. Only the `metadata` attribute
    is read by the parsers."""

    metadata: dict


@dataclass(frozen=True)
class FakeResult:
    """Stand-in for Tier2InvocationResult. Parsers also accept the
    bare envelope; this exercises the .output_envelope passthrough."""

    output_envelope: FakeEnvelope


# ── Darla parser ──────────────────────────────────────────────────


def test_darla_parse_pass_verdict() -> None:
    env = FakeEnvelope(
        metadata={
            "overall": "pass",
            "palette_pass": True,
            "fonts_pass": True,
            "voice_pass": True,
            "asset_pass": True,
            "notes": [],
        }
    )
    a = _parse_attestation(env)
    assert isinstance(a, BrandAttestation)
    assert a.overall == "pass"
    assert a.palette_pass and a.fonts_pass and a.voice_pass and a.asset_pass
    assert a.notes == ()


def test_darla_parse_needs_revision_with_notes() -> None:
    env = FakeEnvelope(
        metadata={
            "overall": "needs_revision",
            "palette_pass": True,
            "fonts_pass": False,
            "voice_pass": True,
            "asset_pass": True,
            "notes": [
                "Body text uses Helvetica; brand requires Barlow.",
                "Heading misses Lexend SemiBold weight.",
            ],
        }
    )
    a = _parse_attestation(env)
    assert a.overall == "needs_revision"
    assert a.fonts_pass is False
    assert len(a.notes) == 2


def test_darla_parse_block_verdict() -> None:
    env = FakeEnvelope(
        metadata={
            "overall": "block",
            "palette_pass": False,
            "fonts_pass": False,
            "voice_pass": False,
            "asset_pass": False,
            "notes": ["Content references a competitor product domain."],
        }
    )
    a = _parse_attestation(env)
    assert a.overall == "block"
    assert not (a.palette_pass or a.fonts_pass or a.voice_pass or a.asset_pass)


def test_darla_parse_off_contract_fails_closed_to_block() -> None:
    env = FakeEnvelope(metadata={"some_other_key": "garbage"})
    a = _parse_attestation(env)
    assert a.overall == "block"
    assert "did not match" in a.notes[0]


def test_darla_parse_unknown_verdict_fails_closed_to_block() -> None:
    env = FakeEnvelope(metadata={"overall": "maybe", "palette_pass": True})
    a = _parse_attestation(env)
    assert a.overall == "block"


def test_darla_parse_accepts_invocation_result_wrapper() -> None:
    env = FakeEnvelope(metadata={"overall": "pass", "palette_pass": True, "fonts_pass": True, "voice_pass": True, "asset_pass": True})
    result = FakeResult(output_envelope=env)
    a = _parse_attestation(result)
    assert a.overall == "pass"


# ── Paul parser ──────────────────────────────────────────────────


def test_paul_parse_primary_dispatch() -> None:
    env = FakeEnvelope(
        metadata={
            "outcome": "primary_dispatch",
            "template_profile_id": "00000000-0000-4000-8000-000010000001",
            "adapter_key": "gamma",
            "fallback_adapter_keys": ["sandbox_pptx"],
            "decision_reason": "Single registered Klear PPTX template; primary Gamma adapter healthy.",
        }
    )
    d = _parse_decision(env, default_adapter_key="gamma")
    assert isinstance(d, PaulDecision)
    assert d.outcome == "primary_dispatch"
    assert d.template_profile_id == "00000000-0000-4000-8000-000010000001"
    assert d.adapter_key == "gamma"
    assert d.fallback_adapter_keys == ("sandbox_pptx",)


def test_paul_parse_fallback_dispatch() -> None:
    env = FakeEnvelope(
        metadata={
            "outcome": "fallback_dispatch",
            "template_profile_id": "00000000-0000-4000-8000-000010000001",
            "adapter_key": "sandbox_pptx",
            "fallback_adapter_keys": [],
            "decision_reason": "Gamma credentials missing for tenant; falling back to sandbox renderer.",
        }
    )
    d = _parse_decision(env, default_adapter_key="gamma")
    assert d.outcome == "fallback_dispatch"
    assert d.adapter_key == "sandbox_pptx"


def test_paul_parse_blocked() -> None:
    env = FakeEnvelope(
        metadata={
            "outcome": "blocked",
            "template_profile_id": None,
            "adapter_key": "gamma",
            "decision_reason": "No template registered for output_kind=md on this tenant; halting publish.",
        }
    )
    d = _parse_decision(env, default_adapter_key="gamma")
    assert d.outcome == "blocked"
    assert d.template_profile_id is None


def test_paul_parse_off_contract_fails_closed_to_blocked() -> None:
    env = FakeEnvelope(metadata={"some_other_key": "garbage"})
    d = _parse_decision(env, default_adapter_key="gamma")
    assert d.outcome == "blocked"
    assert d.adapter_key == "gamma"
    assert "did not match" in d.decision_reason


def test_paul_parse_with_candidate_choice() -> None:
    env = FakeEnvelope(
        metadata={
            "outcome": "primary_dispatch",
            "template_profile_id": "00000000-0000-4000-8000-000010000001",
            "adapter_key": "gamma",
            "candidate_choice": "candidate_b",
            "decision_reason": "Candidate B's executive deck format better matches operator intent.",
        }
    )
    d = _parse_decision(env, default_adapter_key="gamma")
    assert d.candidate_choice == "candidate_b"


# ── DB-backed: brand profile + template choices loaders ───────────


async def _open_tenant_conn(
    db_url: str, *, client_id: str
) -> asyncpg.Connection:
    conn = await asyncpg.connect(db_url)
    await conn.execute("SET LOCAL ROLE iwo3_app")
    await conn.execute(
        f"SET LOCAL app.current_client_id = '{client_id}'"
    )
    return conn


@iwo3_db
def test_darla_loads_klear_brand_profile_text() -> None:
    """Klear's full brand profile yields a structured text block
    Darla can score against."""
    from runtime.darla_qa import _load_brand_profile_text

    async def run() -> None:
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await _open_tenant_conn(url, client_id=KLEAR_CLIENT)
        try:
            text = await _load_brand_profile_text(conn, client_id=KLEAR_CLIENT)
            assert text is not None
            # Klear seed populates palette + fonts + voice + ICP + brand_terms
            assert "PALETTE" in text
            assert "FONTS" in text
            assert "VOICE" in text or "ICP" in text
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_paul_loads_klear_template_choices_for_pptx() -> None:
    """Klear's brand profile registers template_handles_json[pptx] =
    [klear_pptx_primary]; Paul's variant choice space should reflect."""
    from runtime.paul_delivery import _load_brand_template_choices

    async def run() -> None:
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await _open_tenant_conn(url, client_id=KLEAR_CLIENT)
        try:
            choices = await _load_brand_template_choices(
                conn, client_id=KLEAR_CLIENT, output_kind="pptx"
            )
            # Klear seed has exactly 1 PPTX template (klear_pptx_primary)
            assert len(choices) >= 1
            keys = [c["profile_key"] for c in choices]
            assert "klear_pptx_primary" in keys
            # Each choice carries the four expected keys
            for c in choices:
                assert "id" in c
                assert "profile_key" in c
                assert "external_ref" in c
                assert "label" in c
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_paul_loads_pdf_choices_for_klear() -> None:
    """Klear has 2 PDF templates (rmis + claims) per template_handles_json[pdf]."""
    from runtime.paul_delivery import _load_brand_template_choices

    async def run() -> None:
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await _open_tenant_conn(url, client_id=KLEAR_CLIENT)
        try:
            choices = await _load_brand_template_choices(
                conn, client_id=KLEAR_CLIENT, output_kind="pdf"
            )
            assert len(choices) == 2
            keys = sorted(c["profile_key"] for c in choices)
            assert keys == ["klear_pdf_claims", "klear_pdf_rmis"]
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_paul_loads_zero_choices_for_html_on_klear() -> None:
    """Klear has no html template registered yet; choice space empty."""
    from runtime.paul_delivery import _load_brand_template_choices

    async def run() -> None:
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await _open_tenant_conn(url, client_id=KLEAR_CLIENT)
        try:
            choices = await _load_brand_template_choices(
                conn, client_id=KLEAR_CLIENT, output_kind="html"
            )
            assert choices == []
        finally:
            await conn.close()

    asyncio.run(run())


# ── Audit vocabulary: locked event names ──────────────────────────


def test_darla_audit_events_match_lock() -> None:
    """The three Darla audit events (one per verdict) must match the
    canonical vocabulary in `LOOP_CAP_D_PHI6_AUDIT_EVENTS`. This
    locks the `_AUDIT_EVENTS_BY_VERDICT` map against drift."""
    from runtime.darla_qa import _AUDIT_EVENTS_BY_VERDICT

    assert set(_AUDIT_EVENTS_BY_VERDICT.values()) == {
        "darla.qa_passed",
        "darla.qa_needs_revision",
        "darla.qa_blocked",
    }
    # Also check key vocabulary
    assert set(_AUDIT_EVENTS_BY_VERDICT.keys()) == {"pass", "needs_revision", "block"}
