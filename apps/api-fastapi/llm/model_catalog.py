"""Provider model-catalogue cache + chat-capability classification.

WHY THIS EXISTS

`GET /llm/models` proxied straight through to the provider's `/models`
endpoint on every call, with no caching. The Aiden Settings model
picker calls it on every Streamlit rerun — so typing in any field on
that page fired a live request to Groq or OpenRouter. That is a
latency cost on every keystroke-triggered rerun and a rate-limit
exposure for no benefit: a provider's model catalogue changes on the
order of weeks, not seconds.

Operator requirement (2026-09-05): sub-agent models must be picked
from a dropdown of what the wired providers actually offer, "refreshed
on a routine basis" so the list stays current. That is a TTL cache
plus an explicit refresh — not a live fetch per rerun.

CHAT CAPABILITY

A provider's `/models` list is not a list of things you can attach to
a sub-agent. Groq's 14 entries include two Whisper speech-to-text
models, two Orpheus text-to-speech voices and two Llama Prompt Guard
classifiers. Wiring any of those to a Tier-2 sub-agent produces an
agent that cannot hold a conversation, and the failure surfaces much
later as a broken work order.

So each entry carries a `chat_capable` flag. It is ADVISORY: the UI
defaults to chat-capable models but offers "show all", and the API
never filters the list. The classifier is a heuristic over model ids
and context windows — providers publish no capability field on the
OpenAI-compatible `/models` shape — so it must never be a hard gate on
the operator's choice.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional


# ── Chat-capability heuristic ────────────────────────────────────────
#
# Matched against a lowercased model id. Each entry is a family that is
# definitively not a chat completion model on the providers we wire.

_NON_CHAT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"whisper", "speech-to-text"),
    (r"orpheus", "text-to-speech"),
    (r"\btts\b|-tts-|^tts-", "text-to-speech"),
    (r"playai", "text-to-speech"),
    (r"prompt-guard", "prompt classifier"),
    (r"llama-guard", "moderation classifier"),
    (r"^text-embedding|embedding", "embedding"),
    (r"\brerank(er)?\b", "reranker"),
    (r"stable-diffusion|flux|dall-e|sdxl", "image generation"),
    (r"\bmoderation\b", "moderation"),
)

# A chat model needs room for a system prompt plus a conversation.
# IWO3's own Tier-1 prompt alone is several thousand tokens. Anything
# under this is a classifier or an audio model regardless of its name.
_MIN_CHAT_CONTEXT = 2048


def classify_model(
    model_id: str, context_window: Optional[int]
) -> tuple[bool, Optional[str]]:
    """Return `(chat_capable, reason_if_not)`.

    Pure. `reason` is a short human label for the UI caption, never an
    error — the operator can still select the model.
    """
    mid = (model_id or "").lower()
    for pattern, label in _NON_CHAT_PATTERNS:
        if re.search(pattern, mid):
            return False, label
    if isinstance(context_window, int) and 0 < context_window < _MIN_CHAT_CONTEXT:
        return False, f"context window {context_window} too small for a system prompt"
    return True, None


def annotate_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add `chat_capable` + `not_chat_reason` to each catalogue entry."""
    out: list[dict[str, Any]] = []
    for m in models:
        capable, reason = classify_model(m.get("id", ""), m.get("contextWindow"))
        entry = dict(m)
        entry["chat_capable"] = capable
        entry["not_chat_reason"] = reason
        out.append(entry)
    return out


# ── TTL cache ────────────────────────────────────────────────────────
#
# Keyed on (client_id, provider): credentials are resolved per tenant,
# so one tenant's catalogue must never be served to another even though
# the upstream list is usually identical. Process-local by design — a
# restart re-fetches, which is the correct behaviour for a cache whose
# only job is to collapse rerun storms.

ENV_TTL = "IWO3_MODEL_CATALOG_TTL_SECONDS"
DEFAULT_TTL_SECONDS = 6 * 60 * 60  # 6 hours

_CACHE: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}


def ttl_seconds() -> int:
    raw = os.environ.get(ENV_TTL)
    if not raw:
        return DEFAULT_TTL_SECONDS
    try:
        # 0 disables caching entirely (always fetch) — useful in tests.
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def get(
    client_id: str, provider: str, *, now: Optional[float] = None
) -> Optional[tuple[list[dict[str, Any]], float]]:
    """Return `(models, fetched_at)` when a fresh entry exists."""
    ttl = ttl_seconds()
    if ttl == 0:
        return None
    hit = _CACHE.get((client_id, provider))
    if hit is None:
        return None
    fetched_at, models = hit
    if (now or time.time()) - fetched_at > ttl:
        return None
    return models, fetched_at


def put(
    client_id: str,
    provider: str,
    models: list[dict[str, Any]],
    *,
    now: Optional[float] = None,
) -> float:
    fetched_at = now if now is not None else time.time()
    _CACHE[(client_id, provider)] = (fetched_at, models)
    return fetched_at


def get_stale(
    client_id: str, provider: str
) -> Optional[tuple[list[dict[str, Any]], float]]:
    """Return a cached catalogue REGARDLESS of age.

    Review finding 2026-09-05 (P3): the route's "serve stale on refresh
    failure" fallback called `get()`, which enforces the TTL — so once
    six hours had passed there was no stale entry to serve and the
    picker collapsed to manual entry at exactly the moment the fallback
    existed to prevent that. Freshness is the caller's business to
    report (`cached` + `fetched_at` + an explicit error string), not a
    reason to withhold the only data available.
    """
    hit = _CACHE.get((client_id, provider))
    if hit is None:
        return None
    fetched_at, models = hit
    return models, fetched_at


def invalidate(client_id: str, provider: str) -> None:
    _CACHE.pop((client_id, provider), None)


def clear() -> None:
    """Test helper — drop every cached catalogue."""
    _CACHE.clear()
