"""Loop 9 Phase 9.3 — env-injected credential ref parsing + resolution."""

from __future__ import annotations

import pytest

from llm.credentials import (
    LlmCredentialError,
    env_var_from_credential_ref,
    resolve_credential,
)


def test_parses_canonical_ref() -> None:
    assert env_var_from_credential_ref("credential_ref:env:GROQ_API_KEY") == (
        "GROQ_API_KEY"
    )
    assert env_var_from_credential_ref("credential_ref:env:openrouter_key") == (
        "openrouter_key"
    )


def test_rejects_other_schemes() -> None:
    assert env_var_from_credential_ref("env:GROQ_API_KEY") is None
    assert env_var_from_credential_ref("credential_ref:vault:foo") is None
    assert env_var_from_credential_ref("") is None
    assert env_var_from_credential_ref("credential_ref:env:") is None


def test_resolve_uses_isolated_env() -> None:
    val = resolve_credential(
        "credential_ref:env:MY_KEY", env={"MY_KEY": "abc123"}
    )
    assert val == "abc123"


def test_resolve_raises_on_unset_env() -> None:
    with pytest.raises(LlmCredentialError) as ei:
        resolve_credential("credential_ref:env:NEVER_SET", env={})
    assert "NEVER_SET" in str(ei.value)


def test_resolve_raises_on_empty_env() -> None:
    with pytest.raises(LlmCredentialError):
        resolve_credential("credential_ref:env:K", env={"K": ""})


def test_resolve_raises_on_bad_ref() -> None:
    with pytest.raises(LlmCredentialError):
        resolve_credential("env:GROQ_API_KEY", env={"GROQ_API_KEY": "x"})
