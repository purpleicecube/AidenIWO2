"""Loop Eta post-close — template resolver unit tests.

Pure-function coverage for the deterministic Klear/FFAI Gamma template
resolver. No DB, no LLM, no fixtures — feeds synthetic
`TemplateChoice` rows in and asserts the resolution shape.

Real-world failing case captured first: operator wrote
   "I need a 4 slide only Intro deck for Klear.ai - using
    GAMMA Klear.ai Template for PPT"
which previously produced no template_profile_id and made
dispatch_gamma_for_package fall back to Gamma defaults.
"""

from __future__ import annotations

import pytest

from runtime.template_resolver import (
    TemplateChoice,
    resolve_template_for_intake,
)


# ── Fixture template sets matching db/seeds/template_profiles.json ───


KLEAR_TEMPLATES: tuple[TemplateChoice, ...] = (
    TemplateChoice(
        template_profile_id="00000000-0000-4000-8000-000010000001",
        profile_key="klear_pptx_primary",
        output_kind="pptx",
        engine="gamma",
        label="Klear.ai primary PPTX template",
        external_ref="g_onfwfqpb52zcws3",
    ),
    TemplateChoice(
        template_profile_id="00000000-0000-4000-8000-000010000002",
        profile_key="klear_pdf_rmis",
        output_kind="pdf",
        engine="gamma",
        label="RMIS PDF template (ROI / Risk v06)",
        external_ref="g_szfb73vjsyir322",
    ),
    TemplateChoice(
        template_profile_id="00000000-0000-4000-8000-000010000003",
        profile_key="klear_pdf_claims",
        output_kind="pdf",
        engine="gamma",
        label="Claims PDF template (w/ overview 26.03.12)",
        external_ref="g_122ahx4j0eer8lz",
    ),
)


FFAI_TEMPLATES: tuple[TemplateChoice, ...] = (
    TemplateChoice(
        template_profile_id="00000000-0000-4000-8000-000020000001",
        profile_key="ffai_pptx_gamma_basic",
        output_kind="pptx",
        engine="gamma_basic",
        label="FreedomForge.AI generic PPTX stub",
        external_ref=None,
    ),
    TemplateChoice(
        template_profile_id="00000000-0000-4000-8000-000020000002",
        profile_key="ffai_pdf_gamma_basic",
        output_kind="pdf",
        engine="gamma_basic",
        label="FreedomForge.AI generic PDF stub",
        external_ref=None,
    ),
)


# ── Auto-pick (matched) cases ─────────────────────────────────────────


def test_resolves_failing_real_world_intake_to_klear_pptx_primary() -> None:
    """The exact intake that prompted this fix must auto-pick the
    klear_pptx_primary template. This is the regression guard."""
    intake = (
        "I need a 4 slide only Intro deck for Klear.ai - "
        "using GAMMA Klear.ai Template for PPT"
    )
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "matched"
    assert result.match is not None
    assert result.match.profile_key == "klear_pptx_primary"
    assert result.match.output_kind == "pptx"
    assert result.detected_output_kind == "pptx"


def test_resolves_klearai_pptx_alias() -> None:
    intake = "Build a klearai-pptx deck for the executive review"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "matched"
    assert result.match is not None
    assert result.match.profile_key == "klear_pptx_primary"


def test_resolves_rmis_intent_to_klear_pdf_rmis() -> None:
    intake = "Generate the RMIS PDF report for client review"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "matched"
    assert result.match is not None
    assert result.match.profile_key == "klear_pdf_rmis"
    assert result.match.output_kind == "pdf"


def test_resolves_claims_intent_to_klear_pdf_claims() -> None:
    intake = "Render the Klear claims overview PDF for Q2"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "matched"
    assert result.match is not None
    assert result.match.profile_key == "klear_pdf_claims"


def test_resolves_ffai_pptx_alias() -> None:
    intake = "Spin up an ffai pptx deck for the FreedomForge launch"
    result = resolve_template_for_intake(intake, FFAI_TEMPLATES)
    assert result.kind == "matched"
    assert result.match is not None
    assert result.match.profile_key == "ffai_pptx_gamma_basic"


def test_profile_key_verbatim_wins_even_without_aliases() -> None:
    intake = "Use klear_pdf_claims for this one"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "matched"
    assert result.match is not None
    assert result.match.profile_key == "klear_pdf_claims"


# ── Output-kind guard prevents pdf templates winning a deck request ──


def test_pptx_request_does_not_match_pdf_only_template() -> None:
    """Ambiguous 'klear' word + slides intent should still pick pptx,
    not the higher-scoring rmis pdf."""
    intake = "Klear deck slides for the partner conference"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "matched"
    assert result.match is not None
    assert result.match.output_kind == "pptx"


# ── needs_choice escalation when intent is templated but no clear match ──


def test_templated_intent_no_specific_match_returns_choices() -> None:
    """Operator wants a deck but didn't say which Klear template — we
    surface the active candidates instead of silently falling through."""
    intake = "Build me a deck for the executive offsite next month"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "needs_choice"
    # detected_output_kind=pptx → only pptx templates surfaced.
    assert result.detected_output_kind == "pptx"
    keys = {c.profile_key for c in result.choices}
    assert "klear_pptx_primary" in keys
    # PDF candidates filtered out when intent is clearly pptx.
    assert "klear_pdf_rmis" not in keys
    assert "klear_pdf_claims" not in keys


def test_templated_intent_pdf_only_kind_returns_pdf_choices() -> None:
    intake = "Generate a PDF report for the board"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "needs_choice"
    assert result.detected_output_kind == "pdf"
    keys = {c.profile_key for c in result.choices}
    assert "klear_pptx_primary" not in keys
    assert "klear_pdf_rmis" in keys
    assert "klear_pdf_claims" in keys


def test_templated_intent_kind_unknown_returns_all_choices() -> None:
    intake = "I want it on our standard template — operator pick please"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "needs_choice"
    assert result.detected_output_kind is None
    assert {c.profile_key for c in result.choices} == {
        t.profile_key for t in KLEAR_TEMPLATES
    }


# ── no_template degradation when intent isn't templated ─────────────


def test_non_templated_intent_returns_no_template() -> None:
    intake = "Schedule a meeting with the marketing team for Friday"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "no_template"


def test_empty_template_list_returns_no_template() -> None:
    intake = "Build me a klear deck"
    result = resolve_template_for_intake(intake, ())
    assert result.kind == "no_template"


def test_content_brief_request_returns_no_template() -> None:
    intake = "Draft a content brief about our pricing for the GTM team"
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    # 'gtm' doesn't trip the templated-intent regex; intake is clearly
    # a content brief, not a templated deliverable.
    assert result.kind == "no_template"


# ── Threshold guard ──────────────────────────────────────────────────


def test_low_score_below_threshold_does_not_auto_match() -> None:
    """A bare 'klear' alone scores 2 (alias weight) — below the
    auto-pick threshold of 5. With templated intent regex unmatched,
    that should fall through to no_template."""
    intake = "klear stuff"  # no template/deck/pdf word
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "no_template"


@pytest.mark.parametrize(
    "intake,expected_key",
    [
        ("Klear primary deck for partners", "klear_pptx_primary"),
        ("Klear claims report PDF", "klear_pdf_claims"),
        ("Klear RMIS roi pdf", "klear_pdf_rmis"),
    ],
)
def test_parametrized_klear_matches(intake: str, expected_key: str) -> None:
    result = resolve_template_for_intake(intake, KLEAR_TEMPLATES)
    assert result.kind == "matched"
    assert result.match is not None
    assert result.match.profile_key == expected_key
