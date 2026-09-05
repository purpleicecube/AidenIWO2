"""Provider model-catalogue cache + chat-capability classifier.

Two jobs, both introduced 2026-09-05 when sub-agent model selection
moved from a free-text box to a catalogue-driven dropdown:

  1. Stop `GET /llm/models` proxying to the provider on every call. The
     picker re-renders on every Streamlit rerun, so an uncached route
     fired a live Groq/OpenRouter request per keystroke.
  2. Tell chat models apart from the speech, embedding and classifier
     models a provider's `/models` list mixes in. Groq returns 14
     entries of which 6 cannot hold a conversation; wiring one to a
     sub-agent fails much later as a broken work order.
"""

from __future__ import annotations

import pytest

from llm import model_catalog as mc


@pytest.fixture(autouse=True)
def _clean_cache():
    mc.clear()
    yield
    mc.clear()


# ── classifier ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_id",
    [
        "openai/gpt-oss-120b",
        "groq/compound",
        "qwen/qwen3.8-27b",
        "allam-2-7b",
        "anthropic/claude-sonnet-4",
        "meta-llama/llama-3.3-70b-versatile",
    ],
)
def test_chat_models_classified_capable(model_id: str) -> None:
    capable, reason = mc.classify_model(model_id, 131072)
    assert capable is True
    assert reason is None


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("whisper-large-v3", "speech-to-text"),
        ("whisper-large-v3-turbo", "speech-to-text"),
        ("canopylabs/orpheus-v1-english", "text-to-speech"),
        ("playai-tts", "text-to-speech"),
        ("meta-llama/llama-prompt-guard-2-22m", "prompt classifier"),
        ("meta-llama/llama-guard-4-12b", "moderation classifier"),
        ("text-embedding-3-large", "embedding"),
        ("stability/stable-diffusion-xl", "image generation"),
    ],
)
def test_non_chat_families_are_flagged(model_id: str, expected: str) -> None:
    capable, reason = mc.classify_model(model_id, 131072)
    assert capable is False
    assert reason == expected


def test_tiny_context_window_is_not_a_chat_model() -> None:
    """A 512-token window cannot hold IWO3's system prompt, whatever the
    model is called."""
    capable, reason = mc.classify_model("some/classifier", 512)
    assert capable is False
    assert "512" in reason


def test_unknown_context_window_does_not_disqualify() -> None:
    """OpenRouter omits the field for many models. Absence is not
    evidence of incapability."""
    capable, _ = mc.classify_model("some/new-model", None)
    assert capable is True


def test_annotate_preserves_original_fields() -> None:
    out = mc.annotate_models(
        [{"id": "openai/gpt-oss-120b", "name": "x", "contextWindow": 131072}]
    )
    assert out[0]["name"] == "x"
    assert out[0]["contextWindow"] == 131072
    assert out[0]["chat_capable"] is True


def test_annotate_does_not_mutate_the_input() -> None:
    src = [{"id": "whisper-large-v3", "contextWindow": 448}]
    mc.annotate_models(src)
    assert "chat_capable" not in src[0]


# ── cache ────────────────────────────────────────────────────────────


def test_put_then_get_round_trips() -> None:
    mc.put("client-a", "groq", [{"id": "m1"}], now=1000.0)
    hit = mc.get("client-a", "groq", now=1010.0)
    assert hit is not None
    models, fetched_at = hit
    assert models == [{"id": "m1"}]
    assert fetched_at == 1000.0


def test_entry_expires_after_ttl() -> None:
    mc.put("client-a", "groq", [{"id": "m1"}], now=1000.0)
    assert mc.get("client-a", "groq", now=1000.0 + mc.ttl_seconds() + 1) is None


def test_entry_still_live_just_inside_ttl() -> None:
    mc.put("client-a", "groq", [{"id": "m1"}], now=1000.0)
    assert mc.get("client-a", "groq", now=1000.0 + mc.ttl_seconds() - 1) is not None


def test_tenants_do_not_share_a_catalogue() -> None:
    """Credentials resolve per tenant; one tenant's catalogue must never
    be served to another even when the upstream list is identical."""
    mc.put("client-a", "groq", [{"id": "a-only"}], now=1000.0)
    assert mc.get("client-b", "groq", now=1000.0) is None


def test_providers_do_not_share_a_catalogue() -> None:
    mc.put("client-a", "groq", [{"id": "groq-only"}], now=1000.0)
    assert mc.get("client-a", "openrouter", now=1000.0) is None


def test_invalidate_drops_one_entry_only() -> None:
    mc.put("client-a", "groq", [{"id": "m1"}], now=1000.0)
    mc.put("client-a", "openrouter", [{"id": "m2"}], now=1000.0)
    mc.invalidate("client-a", "groq")
    assert mc.get("client-a", "groq", now=1000.0) is None
    assert mc.get("client-a", "openrouter", now=1000.0) is not None


def test_zero_ttl_disables_caching(monkeypatch) -> None:
    """Escape hatch for tests and debugging — always fetch live."""
    monkeypatch.setenv(mc.ENV_TTL, "0")
    mc.put("client-a", "groq", [{"id": "m1"}], now=1000.0)
    assert mc.get("client-a", "groq", now=1000.0) is None


def test_malformed_ttl_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv(mc.ENV_TTL, "not-a-number")
    assert mc.ttl_seconds() == mc.DEFAULT_TTL_SECONDS


# ── stale-on-failure (review finding 2026-09-05, P3) ─────────────────


def test_get_stale_returns_an_expired_entry() -> None:
    """The route's "serve stale on refresh failure" fallback originally
    called `get()`, which enforces the TTL — so once six hours had
    passed there was no stale catalogue to serve, and the picker
    collapsed to manual entry at exactly the moment the fallback existed
    to prevent that. `get_stale()` is age-blind by design; freshness is
    reported to the caller, not used to withhold the only data there is."""
    mc.put("client-a", "groq", [{"id": "m1"}], now=1000.0)
    long_after = 1000.0 + mc.ttl_seconds() * 10
    assert mc.get("client-a", "groq", now=long_after) is None
    hit = mc.get_stale("client-a", "groq")
    assert hit is not None
    models, fetched_at = hit
    assert models == [{"id": "m1"}]
    assert fetched_at == 1000.0


def test_get_stale_still_returns_nothing_when_never_cached() -> None:
    assert mc.get_stale("client-a", "groq") is None


def test_get_stale_respects_tenant_isolation() -> None:
    mc.put("client-a", "groq", [{"id": "a-only"}], now=1000.0)
    assert mc.get_stale("client-b", "groq") is None
