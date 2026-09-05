"""Provider ↔ credential cross-wire guard.

Observed live, 2026-09-05. The operator switched `darla_tier_2` from
openrouter to groq using the new model picker and chose a Groq model.
`credential_ref` was left alone — the form says "leave blank to keep
existing" — so the row saved as:

    provider=groq  credential_ref=credential_ref:env:OPENROUTER_API_KEY

Every invoke then sent the OpenRouter key to api.groq.com and got back
HTTP 401 "Invalid API Key". That error names the key, not the wiring,
so it reads as a dead credential and sends you hunting for a key that
was perfectly good — just pointed at the wrong endpoint.

The picker made switching provider a one-click affair, which turned a
latent hole into an easy one to fall into. These tests hold the guard
that closes it.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from routes.llm import (
    _validate_provider_credential_pair as check,
    expected_env_var,
)


def _detail(exc_info) -> dict:  # noqa: ANN001
    return exc_info.value.detail


# ── the cross-wire it exists to catch ────────────────────────────────


def test_groq_provider_with_openrouter_key_is_rejected() -> None:
    """The exact live failure."""
    with pytest.raises(HTTPException) as ei:
        check("groq", "credential_ref:env:OPENROUTER_API_KEY")
    d = _detail(ei)
    assert d["error"] == "provider_credential_mismatch"
    assert d["credential_belongs_to"] == "openrouter"
    assert d["expected_env_var"] == "GROQ_API_KEY"


def test_openrouter_provider_with_groq_key_is_rejected() -> None:
    with pytest.raises(HTTPException) as ei:
        check("openrouter", "credential_ref:env:GROQ_API_KEY")
    assert _detail(ei)["credential_belongs_to"] == "groq"


def test_rejection_is_400_not_500() -> None:
    """Operator error, not a server fault."""
    with pytest.raises(HTTPException) as ei:
        check("groq", "credential_ref:env:OPENAI_API_KEY")
    assert ei.value.status_code == 400


def test_hint_names_the_fix_not_just_the_problem() -> None:
    """A 401 already tells you something is wrong. The value here is
    saying which field to change and to what."""
    with pytest.raises(HTTPException) as ei:
        check("groq", "credential_ref:env:OPENROUTER_API_KEY")
    hint = _detail(ei)["hint"]
    assert "credential_ref:env:GROQ_API_KEY" in hint
    assert "401" in hint


# ── what it must NOT reject ──────────────────────────────────────────


@pytest.mark.parametrize(
    "provider,ref",
    [
        ("groq", "credential_ref:env:GROQ_API_KEY"),
        ("openrouter", "credential_ref:env:OPENROUTER_API_KEY"),
        ("openai", "credential_ref:env:OPENAI_API_KEY"),
        ("anthropic", "credential_ref:env:ANTHROPIC_API_KEY"),
    ],
)
def test_matching_pairs_pass(provider: str, ref: str) -> None:
    check(provider, ref)


@pytest.mark.parametrize(
    "ref",
    [
        "credential_ref:env:GROQ_KEY_PROD",
        "credential_ref:env:LLM_GATEWAY_SECRET",
        "credential_ref:env:MY_TEAM_KEY",
    ],
)
def test_unconventional_env_names_are_allowed(ref: str) -> None:
    """The guard catches cross-wires, it does not police naming. A
    deployment may call its key anything; rejecting those would break
    legitimate setups for the sake of a convention."""
    check("groq", ref)


def test_malformed_ref_is_left_to_the_format_validator() -> None:
    """`_validate_credential_ref` owns shape errors. This guard must not
    also raise on them, or the operator gets the wrong message."""
    check("groq", "not-a-credential-ref")


def test_case_insensitive_env_name_match() -> None:
    """`groq_api_key` is the same variable as `GROQ_API_KEY` to a human
    writing the config; catch the cross-wire either way."""
    with pytest.raises(HTTPException):
        check("groq", "credential_ref:env:openrouter_api_key")


# ── helper ───────────────────────────────────────────────────────────


def test_expected_env_var_maps_known_providers() -> None:
    assert expected_env_var("groq") == "GROQ_API_KEY"
    assert expected_env_var("openrouter") == "OPENROUTER_API_KEY"


def test_expected_env_var_none_for_unknown_provider() -> None:
    assert expected_env_var("some-future-provider") is None
