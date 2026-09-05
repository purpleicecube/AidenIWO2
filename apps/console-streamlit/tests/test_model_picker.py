"""Sub-agent model picker — catalogue selection rules.

The operator asked for the sub-agent Model field to become a dropdown
driven by the live Groq / OpenRouter catalogues (2026-09-05), replacing
a free-text box where a typo saved cleanly and only surfaced later as a
failed work order.

Swapping free text for a dropdown introduces a failure mode the text
box did not have: a dropdown can only offer what the catalogue lists,
so an agent whose stored model has been retired — or is filtered out by
the chat-capability default — would silently re-point at whatever sits
at index 0 when the operator next presses Save. `visible_models` is the
guard, and these are its tests.
"""

from __future__ import annotations

from model_picker import visible_models


CHAT_A = {"id": "openai/gpt-oss-120b", "chat_capable": True}
CHAT_B = {"id": "qwen/qwen3.8-27b", "chat_capable": True}
CHAT_C = {"id": "groq/compound", "chat_capable": True}
WHISPER = {
    "id": "whisper-large-v3",
    "chat_capable": False,
    "not_chat_reason": "speech-to-text",
}
CATALOG = [CHAT_A, CHAT_B, CHAT_C, WHISPER]


def ids(rows: list[dict]) -> list[str]:
    return [r["id"] for r in rows]


# ── the load-bearing invariant ───────────────────────────────────────


def test_current_model_is_always_present_and_first() -> None:
    out = visible_models(
        CATALOG, current_model="qwen/qwen3.8-27b", show_all=False, query=""
    )
    assert out[0]["id"] == "qwen/qwen3.8-27b"


def test_retired_model_is_kept_and_flagged_not_dropped() -> None:
    """The provider stopped publishing the agent's model. It must still
    be offered — losing it would silently re-point the agent."""
    out = visible_models(
        CATALOG, current_model="qwen/qwen2-legacy", show_all=False, query=""
    )
    assert out[0]["id"] == "qwen/qwen2-legacy"
    assert out[0]["_missing_from_catalog"] is True


def test_current_model_survives_the_capability_filter() -> None:
    """Someone deliberately wired a non-chat model. Hiding it by default
    must not silently swap it for a chat model on the next save."""
    out = visible_models(
        CATALOG, current_model="whisper-large-v3", show_all=False, query=""
    )
    assert out[0]["id"] == "whisper-large-v3"


def test_current_model_survives_a_non_matching_filter() -> None:
    """Operator types a filter that excludes the stored model. The
    dropdown must not quietly drop to a different default."""
    out = visible_models(
        CATALOG, current_model="openai/gpt-oss-120b", show_all=False, query="qwen"
    )
    assert out[0]["id"] == "openai/gpt-oss-120b"
    assert "qwen/qwen3.8-27b" in ids(out)


def test_current_model_appears_exactly_once() -> None:
    """Hoisting must not duplicate the entry — a duplicate option makes
    the selectbox index ambiguous."""
    out = visible_models(
        CATALOG, current_model="groq/compound", show_all=True, query=""
    )
    assert ids(out).count("groq/compound") == 1


# ── ordinary filtering ───────────────────────────────────────────────


def test_non_chat_models_hidden_by_default() -> None:
    out = visible_models(CATALOG, current_model="", show_all=False, query="")
    assert "whisper-large-v3" not in ids(out)
    assert len(out) == 3


def test_show_all_reveals_non_chat_models() -> None:
    out = visible_models(CATALOG, current_model="", show_all=True, query="")
    assert "whisper-large-v3" in ids(out)


def test_query_narrows_by_substring() -> None:
    out = visible_models(CATALOG, current_model="", show_all=False, query="qwen")
    assert ids(out) == ["qwen/qwen3.8-27b"]


def test_query_is_case_insensitive_on_the_catalogue_side() -> None:
    out = visible_models(
        [{"id": "Meta-Llama/Llama-3", "chat_capable": True}],
        current_model="",
        show_all=False,
        query="llama",
    )
    assert len(out) == 1


def test_no_current_model_returns_plain_filtered_pool() -> None:
    """A brand-new config has no stored model; nothing to preserve."""
    out = visible_models(CATALOG, current_model="", show_all=False, query="")
    assert ids(out) == ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "groq/compound"]


def test_models_lacking_the_capability_flag_are_treated_as_chat() -> None:
    """An older API build returns no `chat_capable`. Defaulting it to
    False would empty the dropdown; default to True."""
    out = visible_models(
        [{"id": "some/model"}], current_model="", show_all=False, query=""
    )
    assert ids(out) == ["some/model"]
