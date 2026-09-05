"""Provider-catalogue model picker for LLM config forms.

Operator requirement (2026-09-05): sub-agent models must be chosen from
a dropdown of what the wired providers (Groq, OpenRouter) actually
offer, refreshed routinely, rather than typed free-hand into a text box
where a typo saves cleanly and only surfaces later as a failed work
order.

DESIGN RULES

1. NEVER silently change the model. If the operator does not touch the
   picker, the value returned is byte-identical to what was stored —
   including a model the provider has since retired, which is kept in
   the list, pre-selected and flagged rather than dropped. Silently
   re-pointing a sub-agent at a neighbouring model because its own one
   vanished from the catalogue would be far worse than showing a
   stale-looking entry.
2. ALWAYS leave an escape hatch. Manual entry stays one click away for
   a brand-new model id the catalogue has not published yet, and is the
   automatic fallback when the provider has no key or the lookup fails.
3. Capability filtering is a DEFAULT, not a gate. Speech, embedding and
   classifier models sit behind "include non-chat models" — the
   operator can still pick one.

`views/aiden_settings.py` keeps its own separate picker by operator
instruction ("I'm okay with having Aiden stay the way he is currently
wired up"). It benefits from the backend catalogue cache automatically,
with no code change. Consolidating the two is a follow-on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import streamlit as st

from api_client import APIError


# Bump to invalidate every cached catalogue in this browser session —
# incremented by the Refresh button.
_TOKEN_KEY = "model-catalog-token"


def _token() -> int:
    return int(st.session_state.get(_TOKEN_KEY, 0))


def bump_token() -> None:
    st.session_state[_TOKEN_KEY] = _token() + 1


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_catalog(
    _api, provider: str, base_url: str, token: int, refresh: bool
) -> dict[str, Any]:
    """Cached fetch. `_api` is underscore-prefixed so Streamlit does not
    try to hash the client. `token` participates in the cache key purely
    so Refresh can force a miss; `base_url` keeps environments from
    sharing an entry."""
    return _api.list_provider_models(provider=provider, refresh=refresh)


def _as_of(fetched_at: Optional[float], cached: bool) -> str:
    if not fetched_at:
        return "live"
    stamp = datetime.fromtimestamp(fetched_at, tz=timezone.utc).strftime("%H:%M UTC")
    return f"{'cached' if cached else 'live'} · as of {stamp}"


def _label(model: dict[str, Any], current: str) -> str:
    mid = model["id"]
    bits: list[str] = [mid]
    ctx = model.get("contextWindow")
    if isinstance(ctx, int) and ctx > 0:
        bits.append(f"{ctx // 1000}k ctx" if ctx >= 1000 else f"{ctx} ctx")
    if not model.get("chat_capable", True):
        bits.append(f"⚠ {model.get('not_chat_reason') or 'not a chat model'}")
    if model.get("_missing_from_catalog"):
        bits.append("⚠ not in provider catalogue")
    if mid == current:
        bits.append("current")
    return "  ·  ".join(bits)


def visible_models(
    models: list[dict[str, Any]],
    *,
    current_model: str,
    show_all: bool,
    query: str,
) -> list[dict[str, Any]]:
    """Which catalogue entries the dropdown offers, in order.

    Pure — this is the safety-critical half of the picker and is unit
    tested without Streamlit.

    Invariant (design rule 1): when `current_model` is set it is ALWAYS
    present in the result, and first, no matter what the capability
    default or the filter would otherwise do. A dropdown that omits the
    stored value silently re-points the agent at whatever sits at
    index 0 the moment the operator saves.

    A `current_model` the provider no longer publishes is synthesised
    into the list carrying `_missing_from_catalog`, so the UI can flag
    it rather than lose it.
    """
    pool = [m for m in models if show_all or m.get("chat_capable", True)]
    if query:
        pool = [m for m in pool if query in m["id"].lower()]

    if not current_model:
        return pool
    if any(m["id"] == current_model for m in pool):
        # Already present — hoist it to the front for discoverability.
        keep = next(m for m in pool if m["id"] == current_model)
        return [keep] + [m for m in pool if m["id"] != current_model]

    known = next((m for m in models if m["id"] == current_model), None)
    if known is None:
        known = {"id": current_model, "_missing_from_catalog": True}
    return [known] + pool


def render_model_picker(
    api,
    *,
    provider: str,
    current_model: str,
    key_prefix: str,
    disabled: bool = False,
    base_url: str = "",
) -> str:
    """Render the Model control and return the chosen model id.

    Returns `current_model` unchanged on every failure path, so a
    provider outage can never rewrite a sub-agent's model.
    """
    manual_key = f"{key_prefix}-manual"
    manual_mode = bool(st.session_state.get(manual_key, False))

    try:
        resp = _fetch_catalog(api, provider, base_url or "", _token(), False)
    except APIError as err:
        chosen = st.text_input(
            "Model",
            value=current_model,
            key=f"{key_prefix}-model-err",
            disabled=disabled,
        )
        st.caption(
            f"⚠️ _catalogue lookup failed ({err.status_code} — {err.detail}); "
            "typed entry only. Existing model preserved._"
        )
        return chosen or current_model

    key_configured = bool(resp.get("keyConfigured"))
    models: list[dict[str, Any]] = list(resp.get("models") or [])
    fetch_error = resp.get("error")

    if not key_configured or not models or manual_mode:
        chosen = st.text_input(
            "Model",
            value=current_model,
            key=f"{key_prefix}-model-manual",
            disabled=disabled,
            placeholder="e.g. openai/gpt-oss-120b",
        )
        if not key_configured:
            st.caption(
                f"_No enabled `{provider}` config in this tenant, or its credential "
                "env var is unset — the catalogue can't be listed. Typed entry only._"
            )
        elif not models:
            st.caption(
                "_Provider returned no models"
                + (f" ({fetch_error})" if fetch_error else "")
                + "._"
            )
        else:
            if st.button(
                "Browse catalogue",
                key=f"{key_prefix}-browse",
                disabled=disabled,
            ):
                st.session_state[manual_key] = False
                st.rerun()
        return chosen or current_model

    # ── Dropdown path ────────────────────────────────────────────────
    show_all = st.checkbox(
        "Include non-chat models (speech, embedding, classifiers)",
        value=False,
        key=f"{key_prefix}-showall",
        disabled=disabled,
    )
    query = (
        st.text_input(
            "Filter models",
            value="",
            key=f"{key_prefix}-filter",
            placeholder="type to narrow the list…",
            disabled=disabled,
        )
        .strip()
        .lower()
    )
    visible = visible_models(
        models, current_model=current_model, show_all=show_all, query=query
    )

    if not visible:
        st.caption("_No models match that filter._")
        return current_model

    ids = [m["id"] for m in visible]
    try:
        index = ids.index(current_model)
    except ValueError:
        index = 0

    chosen = st.selectbox(
        "Model",
        options=ids,
        index=index,
        format_func=lambda mid: _label(
            next(m for m in visible if m["id"] == mid), current_model
        ),
        key=f"{key_prefix}-model-select",
        disabled=disabled,
    )

    note = (
        f"_{len(models)} models from `{provider}` · "
        f"{_as_of(resp.get('fetched_at'), bool(resp.get('cached')))}_"
    )
    if fetch_error:
        note += f" · ⚠️ {fetch_error}"
    st.caption(note)
    return chosen or current_model


def render_catalog_controls(api, *, provider: str, key_prefix: str, disabled: bool = False) -> None:
    """Refresh / manual-entry controls.

    Rendered OUTSIDE the config `st.form` — Streamlit forbids
    `st.button` inside a form, and these act immediately rather than on
    submit.
    """
    left, right, _ = st.columns([1, 1, 3])
    with left:
        if st.button(
            "↻ Refresh catalogue",
            key=f"{key_prefix}-refresh",
            disabled=disabled,
            help=f"Re-fetch the live {provider} model list, bypassing the cache.",
        ):
            try:
                api.list_provider_models(provider=provider, refresh=True)
            except APIError as err:
                st.warning(f"Refresh failed: {err.status_code} — {err.detail}")
            _fetch_catalog.clear()
            bump_token()
            st.rerun()
    with right:
        manual_key = f"{key_prefix}-manual"
        if st.session_state.get(manual_key, False):
            if st.button("Browse catalogue", key=f"{key_prefix}-browse-out", disabled=disabled):
                st.session_state[manual_key] = False
                st.rerun()
        else:
            if st.button("Enter manually", key=f"{key_prefix}-manual-btn", disabled=disabled):
                st.session_state[manual_key] = True
                st.rerun()
