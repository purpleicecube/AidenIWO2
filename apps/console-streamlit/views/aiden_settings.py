"""Aiden Settings — IWO2 visual idiom matched to client/src/pages/settings.tsx.

Architect lock 2026-04-26 §D2 (`IWO3_DESIGN_MEGALOOP_ARCHITECT_LOCK_v0.1.0`):
visual parity first, backend parity preserved, abstraction deferred.
Page 2/7 of the IWO3 Design MegaLoop.

IWO2 settings.tsx is a single max-w-3xl centered Card with header
badge + body form for the Aiden LLM. IWO3 has additional sections
(tenant ceiling, persona library, channel bindings) which are
IWO3-native; they inherit the IWO2 Card idiom + spacing for
consistency rather than getting a separate visual treatment.

Backend wiring unchanged from prior alpha/beta versions:
  - GET  /llm/providers
  - GET  /llm/configs            (filtered to aiden_tier_1)
  - PATCH /llm/configs/{id}      (system:admin)
  - POST /llm/test               (system:admin)
  - GET  /tenants/me/settings    (client:read)
  - PATCH /tenants/me/settings   (system:admin)
  - GET  /llm/personas           (client:read)
  - POST /channel/auth_codes     (channel_auth_code:issue)
  - GET  /channel/identities
  - POST /channel/identities/{id}/revoke (channel_identity:revoke)

RBAC gating preserved: every disabled control is server-enforced.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


_CHANNEL_KINDS = ["telegram", "slack", "email", "sms"]
_PROVIDER_OPTIONS = ["groq", "openrouter", "openai", "anthropic"]


# ── Lucide-style inline SVG icons ────────────────────────────────────
# Path data sourced from Lucide (MIT). 24x24 viewBox, stroke-based.

_PATHS = {
    "brain": (
        '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>'
        '<path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>'
        '<path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/>'
        '<path d="M17.599 6.5a3 3 0 0 0 .399-1.375"/>'
        '<path d="M6.003 5.125A3 3 0 0 0 6.401 6.5"/>'
        '<path d="M3.477 10.896a4 4 0 0 1 .585-.396"/>'
        '<path d="M19.938 10.5a4 4 0 0 1 .585.396"/>'
        '<path d="M6 18a4 4 0 0 1-1.967-.516"/>'
        '<path d="M19.967 17.484A4 4 0 0 1 18 18"/>'
    ),
    "key_round": (
        '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"/>'
        '<circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>'
    ),
    "users": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "radio": (
        '<path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/>'
        '<path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/>'
        '<circle cx="12" cy="12" r="2"/>'
        '<path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/>'
        '<path d="M19.1 4.9C23 8.8 23 15.2 19.1 19.1"/>'
    ),
    "save": (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<polyline points="17 21 17 13 7 13 7 21"/>'
        '<polyline points="7 3 7 8 15 8"/>'
    ),
    "zap": (
        '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'
    ),
    "check_circle": (
        '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>'
        '<polyline points="22 4 12 14.01 9 11.01"/>'
    ),
    "alert_triangle": (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
        '<line x1="12" x2="12" y1="9" y2="13"/>'
        '<line x1="12" x2="12.01" y1="17" y2="17"/>'
    ),
    "circle_dot": (
        '<circle cx="12" cy="12" r="10"/>'
        '<circle cx="12" cy="12" r="2" fill="currentColor"/>'
    ),
}


def _svg(name: str, *, size: int = 16, color: Optional[str] = None) -> str:
    body = _PATHS.get(name, "")
    style = f' style="color:{color};"' if color else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"{style}>{body}</svg>'
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _credential_badge_html(state: str, env_name: Optional[str]) -> str:
    if state == "set":
        icon = _svg("check_circle", size=12, color="#1E5F91")
        text = f"ENV {env_name} set" if env_name else "API Key Set"
        cls = "set"
    elif state == "missing":
        icon = _svg("alert_triangle", size=12, color="#B45309")
        text = f"ENV {env_name} missing" if env_name else "Key Missing"
        cls = "missing"
    else:
        icon = _svg("alert_triangle", size=12, color="#B45309")
        text = "credential_ref malformed"
        cls = "missing"
    return (
        f'<span class="settings-badge settings-badge-{cls}">'
        f'<span class="settings-badge-icon">{icon}</span>'
        f'<span>{text}</span></span>'
    )


def _ceiling_badge_html(is_default: bool, current: int) -> str:
    if is_default:
        icon = _svg("circle_dot", size=10, color="#94a3b8")
        text = f"platform default · {current:,}"
        cls = "neutral"
    else:
        icon = _svg("circle_dot", size=10, color="#1E5F91")
        text = f"tenant override · {current:,}"
        cls = "set"
    return (
        f'<span class="settings-badge settings-badge-{cls}">'
        f'<span class="settings-badge-icon">{icon}</span>'
        f'<span>{text}</span></span>'
    )


def _rbac_lockout_banner(decision, *, permission: str, action_label: str) -> None:  # noqa: ANN001
    """Render an amber explanation banner inside a card when an RBAC
    decision blocks the section's primary action. Without this, buttons
    just look mystery-disabled."""
    if decision.allowed:
        return
    icon = _svg("alert_triangle", size=12, color="#B45309")
    st.markdown(
        f"""
        <div class="settings-rbac-banner">
          <span class="settings-rbac-icon">{icon}</span>
          <div class="settings-rbac-body">
            <strong>{action_label} disabled</strong> — your role
            <code>{decision.role}</code> does not include
            <code>{permission}</code>. Sign in as a role that carries
            this permission to make changes.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section_header(*, icon: str, title: str, badge_html: str = "") -> None:
    """Card header — icon + title on the left, optional badge on the
    right. Mirrors IWO2's `<CardHeader>` flex-row idiom."""
    icon_svg = _svg(icon, size=14, color="#1E5F91")
    st.markdown(
        f"""
        <div class="settings-card-header">
          <div class="settings-card-title">
            <span class="settings-card-icon">{icon_svg}</span>
            <span>{title}</span>
          </div>
          <div class="settings-card-badges">{badge_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Section 1 — Aiden LLM (mirrors IWO2 settings.tsx Card) ───────────


def _render_model_picker(
    api,  # noqa: ANN001
    *,
    provider: str,
    current_model: str,
    disabled: bool,
) -> str:
    """IWO2-faithful model picker.

    Mirrors `client/src/components/model-selector.tsx`:
      - Loads models for the selected provider via GET /llm/models.
      - When `keyConfigured=false` → manual text input + caption.
      - When models load → alphabetical dropdown; filter input above the
        list when the catalog has more than 10 models.
      - "Browse models ↔ Enter manually" toggle so the user can always
        type a model id the catalog doesn't surface.

    Returns the chosen model id (caller threads this into the Save patch)."""

    manual_key = f"model-manual-{provider}"
    manual_mode = st.session_state.get(manual_key, False)

    # Cheap fetch — Streamlit reruns on every interaction; the route is
    # local to the FastAPI runtime so latency is negligible. If profiling
    # later shows churn, add `@st.cache_data(ttl=300)` keyed on (provider,
    # api.base_url) — see api_client.list_provider_models docstring.
    try:
        resp = api.list_provider_models(provider=provider)
    except APIError as err:
        st.text_input(
            "Model",
            value=current_model,
            key=f"model-text-fallback-{provider}",
            disabled=disabled,
        )
        st.caption(f"_models lookup failed: {err.status_code} — typed entry only._")
        return st.session_state.get(f"model-text-fallback-{provider}", current_model)

    key_configured = bool(resp.get("keyConfigured"))
    models = resp.get("models") or []
    fetch_error = resp.get("error")

    if not key_configured or manual_mode:
        # Manual text input
        manual_value = st.text_input(
            "Model",
            value=current_model,
            key=f"model-text-{provider}",
            disabled=disabled,
            placeholder="e.g. llama-3.3-70b-versatile",
        )
        if not key_configured:
            if fetch_error:
                st.caption(
                    f"_API key not set for `{provider}` ({fetch_error}). "
                    "Type a model ID manually or set the env var on the FastAPI runtime._"
                )
            else:
                st.caption(
                    f"_No active config for `{provider}` in this tenant, or its credential env "
                    "var isn't set. Type a model ID manually._"
                )
        else:
            if st.button(
                "Browse available models",
                key=f"browse-models-{provider}",
                disabled=disabled,
            ):
                st.session_state[manual_key] = False
                st.rerun()
        return manual_value

    # Dropdown path — keyConfigured=true and not manual mode
    sorted_ids = sorted([m["id"] for m in models], key=str.lower)

    if len(sorted_ids) > 10:
        filt = st.text_input(
            "Filter",
            key=f"model-filter-{provider}",
            placeholder="filter models…",
            label_visibility="collapsed",
        )
        if filt:
            lf = filt.lower()
            sorted_ids = [m for m in sorted_ids if lf in m.lower()]

    if not sorted_ids:
        st.caption("_No models match the filter._")
        return current_model

    if current_model in sorted_ids:
        idx = sorted_ids.index(current_model)
    else:
        idx = 0

    chosen = st.selectbox(
        "Model",
        sorted_ids,
        index=idx,
        key=f"model-select-{provider}",
        disabled=disabled,
    )
    cap_cols = st.columns([5, 2])
    with cap_cols[0]:
        st.caption(f"_{len(models)} models available · sorted alphabetically_")
    with cap_cols[1]:
        if st.button(
            "Enter manually",
            key=f"manual-models-{provider}",
            disabled=disabled,
            use_container_width=True,
        ):
            st.session_state[manual_key] = True
            st.rerun()
    return chosen


def _section_aiden_config(api) -> None:  # noqa: ANN001
    try:
        configs = api.list_llm_configs()
        providers = api.list_llm_providers()
        # Beta-2 phase 0.3.5 RBAC fix: editing is gated by `llm_config:write`,
        # not `system:admin`. Connection-test gates on the same. Ref CODEX
        # 2026-05-01 finding 5.
        can_admin = api.check_permission("llm_config:write")
    except APIError as err:
        with st.container(border=True):
            _section_header(icon="brain", title="LLM Provider")
            st.error(f"{err.status_code} — {err.detail}")
        return

    aiden = next((c for c in configs if c["agent_role"] == "aiden_tier_1"), None)
    if aiden is None:
        with st.container(border=True):
            _section_header(icon="brain", title="LLM Provider")
            st.warning(
                "No `aiden_tier_1` config for this tenant. Add one via the "
                "Sub-Agents page → New sub-agent before using Chat with Aiden."
            )
        return

    state = aiden["credential_state"]
    env_name = aiden.get("env_var_name")
    badge_html = _credential_badge_html(state, env_name)

    with st.container(border=True):
        _section_header(icon="brain", title="LLM Provider", badge_html=badge_html)
        st.caption(
            f"Aiden Tier 1 · `{aiden['id'][:8]}…` · provider `{aiden['provider']}` · model `{aiden['model']}`"
        )

        _rbac_lockout_banner(
            can_admin,
            permission="llm_config:write",
            action_label="Save / Test connection",
        )

        # Provider availability chips — IWO3 extra (IWO2 doesn't have
        # this). Render as a single inline row so it doesn't dominate.
        if providers:
            chip_html = []
            for p in providers:
                tone = "set" if p.get("callable_in_phase_9_3") else "neutral"
                dot_color = "#1E5F91" if p.get("callable_in_phase_9_3") else "#94a3b8"
                chip_html.append(
                    f'<span class="settings-pchip settings-pchip-{tone}">'
                    f'{_svg("circle_dot", size=8, color=dot_color)}'
                    f'<span>{p["name"]}</span></span>'
                )
            st.markdown(
                f'<div class="settings-pchip-row">{"".join(chip_html)}</div>',
                unsafe_allow_html=True,
            )

        # Bordered enable-toggle row (IWO2 idiom)
        toggle_cols = st.columns([5, 1])
        with toggle_cols[0]:
            st.markdown(
                """
                <div class="settings-toggle-text">
                  <div class="settings-toggle-title">Enable Aiden LLM</div>
                  <div class="settings-toggle-sub">When enabled, Aiden uses the LLM for Tier 1 / Tier 2 decisions. When disabled, hardcoded rules are used.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with toggle_cols[1]:
            new_enabled = st.toggle(
                "enabled",
                value=aiden["enabled"],
                key="aiden-enable-toggle",
                label_visibility="collapsed",
                disabled=not can_admin.allowed,
            )

        # ── Provider + Model selectors live OUTSIDE the form so the
        # model picker can react to provider changes. Streamlit forms
        # batch widget updates, so an in-form selectbox can't drive a
        # reactive model dropdown. The form below picks up these values
        # via closure on submit.
        prov_col, model_col = st.columns(2)
        with prov_col:
            provider = st.selectbox(
                "Provider",
                _PROVIDER_OPTIONS,
                index=(
                    _PROVIDER_OPTIONS.index(aiden["provider"])
                    if aiden["provider"] in _PROVIDER_OPTIONS
                    else 0
                ),
                key="aiden-provider",
                disabled=not can_admin.allowed,
            )
        with model_col:
            model = _render_model_picker(
                api,
                provider=provider,
                current_model=aiden["model"],
                disabled=not can_admin.allowed,
            )

        with st.form("aiden-edit", clear_on_submit=False, border=False):
            col1, col2 = st.columns(2)
            with col1:
                display_name = st.text_input("Display name", value=aiden["display_name"])
            with col2:
                base_url = st.text_input(
                    "Base URL (optional)",
                    value=aiden.get("base_url") or "",
                    placeholder="leave empty for default endpoint",
                )

            credential_ref = st.text_input(
                "Credential ref",
                value="",
                placeholder=f"Currently {env_name or '—'}. Leave blank to keep existing.",
                help="Format: `credential_ref:env:NAME`. The runtime reads the API key from that env var.",
            )

            description = st.text_area(
                "Description", value=aiden.get("description") or "", height=68
            )

            # IWO2-style API-key info bar
            st.markdown(
                f"""
                <div class="settings-keybar">
                  <span class="settings-keybar-icon">{_svg("key_round", size=14, color="#6b7280")}</span>
                  <div class="settings-keybar-body">
                    Set your API key as the env var <code>{env_name or "&lt;not set&gt;"}</code> in the runtime environment. The console never reads or stores raw key material; only the <code>credential_ref:env:NAME</code> placeholder lives in the DB.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown('<hr class="settings-sep" />', unsafe_allow_html=True)

            # Beta-2 phase 0.3.1 — pre-load the actual prompt body (writer-gated)
            # so the operator can see and edit, not blind-overwrite.
            current_prompt = ""
            prompt_load_error: Optional[str] = None
            if can_admin.allowed:
                try:
                    pr = api.get_llm_config_prompt(aiden["id"])
                    current_prompt = pr.get("system_prompt") or ""
                except APIError as err:
                    prompt_load_error = f"{err.status_code} — {err.detail}"

            if prompt_load_error:
                st.warning(
                    f"Could not load current system prompt: {prompt_load_error}"
                )

            st.markdown(
                f"**System prompt** &nbsp;·&nbsp; "
                f"<span style='color:#6b7280; font-size: 0.8rem;'>"
                f"{len(current_prompt)} chars currently stored"
                f"</span>",
                unsafe_allow_html=True,
            )
            prompt_action = st.radio(
                "What do you want to do with the system prompt?",
                options=["Keep unchanged", "Replace with new prompt", "Clear (reset to default)"],
                index=0,
                horizontal=True,
                label_visibility="collapsed",
                key=f"aiden-prompt-action-{aiden['id']}",
            )
            system_prompt = st.text_area(
                "System prompt",
                value=current_prompt,
                height=240,
                disabled=prompt_action != "Replace with new prompt",
                help=(
                    "Defines how Aiden evaluates work orders at both tiers. "
                    "Pick \"Replace\" to edit; \"Clear\" to drop back to the "
                    "runtime default; \"Keep unchanged\" to leave as-is."
                ),
                label_visibility="collapsed",
            )
            change_reason = st.text_input(
                "Change reason (optional, recorded in version history)",
                value="",
                placeholder="e.g. 'Tightened brevity rules per Klear feedback'",
            )

            action_cols = st.columns([1, 1, 4])
            with action_cols[0]:
                save = st.form_submit_button(
                    "Save",
                    type="primary",
                    disabled=not can_admin.allowed,
                    use_container_width=True,
                )
            with action_cols[1]:
                test = st.form_submit_button(
                    "Test connection",
                    disabled=not can_admin.allowed,
                    use_container_width=True,
                )

        if save:
            patch = {
                "provider": provider,
                "model": model,
                "base_url": base_url or None,
                "enabled": new_enabled,
                "display_name": display_name,
                "description": description or None,
            }
            if credential_ref.strip():
                patch["credential_ref"] = credential_ref.strip()
            # Beta-2 phase 0.3.2 tri-state contract — the API now requires
            # explicit prompt_action whenever system_prompt is in the body.
            if prompt_action == "Replace with new prompt":
                patch["prompt_action"] = "set"
                patch["system_prompt"] = system_prompt
            elif prompt_action == "Clear (reset to default)":
                patch["prompt_action"] = "clear"
            else:
                patch["prompt_action"] = "unchanged"
            if change_reason.strip():
                patch["change_reason"] = change_reason.strip()
            try:
                api.update_llm_config(aiden["id"], **patch)
                st.success("Saved. New version row written for rollback.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.status_code} — {err.detail}")
        elif test:
            try:
                r = api.test_llm(agent_role="aiden_tier_1")
            except APIError as err:
                st.error(f"{err.status_code} — {err.detail}")
            else:
                if r.get("ok"):
                    st.success(
                        f"Connected · {r['provider']}/{r['model']} · {r['latency_ms']}ms"
                    )
                else:
                    st.warning(f"{r.get('error')}")


# ── Section 2 — Per-tenant LLM ceiling (Q1) ──────────────────────────


def _section_tenant_ceiling(api) -> None:  # noqa: ANN001
    try:
        settings = api.get_my_tenant_settings()
        can_admin = api.check_permission("system:admin")
    except APIError as err:
        with st.container(border=True):
            _section_header(icon="key_round", title="Per-tenant LLM ceiling")
            st.error(f"{err.status_code} — {err.detail}")
        return

    current = int(settings["llm_per_wo_ceiling"])
    is_default = bool(settings["llm_per_wo_ceiling_is_default"])
    cmin = int(settings.get("ceiling_min", 1_000))
    cmax = int(settings.get("ceiling_max", 1_000_000))
    badge_html = _ceiling_badge_html(is_default, current)

    with st.container(border=True):
        _section_header(icon="key_round", title="Per-tenant LLM ceiling", badge_html=badge_html)
        st.caption(
            f"`{settings['designation']}` · per-WO budget cap. "
            f"Allowed range {cmin:,}–{cmax:,} tokens."
        )

        if not can_admin.allowed:
            st.caption(
                f"_Read-only — `system:admin` required to change (your role: {can_admin.role})._"
            )
            return

        with st.form("tenant-ceiling-edit", clear_on_submit=False, border=False):
            cols = st.columns([2, 1])
            with cols[0]:
                new_value = st.number_input(
                    "New per-WO ceiling (tokens)",
                    min_value=cmin,
                    max_value=cmax,
                    value=current,
                    step=1_000,
                )
            with cols[1]:
                revert = st.checkbox(
                    "Revert to platform default",
                    value=False,
                    help="Clear the tenant override and fall back to DEFAULT_PER_WO_CEILING.",
                )
            save = st.form_submit_button("Save", type="primary", use_container_width=False)

        if save:
            try:
                if revert:
                    api.update_my_tenant_settings(revert_to_default=True)
                    st.success("Reverted to platform default.")
                else:
                    api.update_my_tenant_settings(llm_per_wo_ceiling=int(new_value))
                    st.success(f"Saved. New ceiling = {int(new_value):,} tokens.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.status_code} — {err.detail}")


# ── Section 3 — Persona library (Q6, read-only) ──────────────────────


def _section_persona_library(api) -> None:  # noqa: ANN001
    try:
        personas = api.list_personas()
    except APIError as err:
        with st.container(border=True):
            _section_header(icon="users", title="Persona library")
            st.error(f"{err.status_code} — {err.detail}")
        return

    count_badge = (
        f'<span class="settings-badge settings-badge-neutral">'
        f'<span>{len(personas)} active</span></span>'
    )

    with st.container(border=True):
        _section_header(icon="users", title="Persona library", badge_html=count_badge)
        st.caption(
            "Reads `prompt_profiles` for this tenant. Editing flows through the existing prompt-profile surfaces."
        )

        if not personas:
            st.caption(
                "No active personas. Create one via the Sub-Agents → Personas surface."
            )
            return

        by_scope: dict[str, list[dict]] = {}
        for p in personas:
            by_scope.setdefault(p["scope"], []).append(p)
        for scope in ("client", "workflow", "wo"):
            rows = by_scope.get(scope) or []
            if not rows:
                continue
            st.markdown(
                f'<div class="settings-persona-scope">Scope · <code>{scope}</code></div>',
                unsafe_allow_html=True,
            )
            for p in rows:
                st.markdown(
                    f'<div class="settings-persona-row">'
                    f'<span class="settings-persona-name">{p["display_name"]}</span>'
                    f'<span class="settings-persona-key">{p["profile_key"]}</span>'
                    f'<span class="settings-persona-status">{p["status"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ── Section 4 — Channel auth codes + bound identities ────────────────


def _section_channels(api) -> None:  # noqa: ANN001
    try:
        can_issue = api.check_permission("channel_auth_code:issue")
        can_revoke = api.check_permission("channel_identity:revoke")
        identities = api.list_channel_identities(only_active=False)
    except APIError as err:
        with st.container(border=True):
            _section_header(icon="radio", title="Channel bindings")
            st.error(f"{err.status_code} — {err.detail}")
        return

    active_count = sum(1 for i in identities if i.get("status") == "active")
    badge_html = (
        f'<span class="settings-badge settings-badge-{"set" if active_count else "neutral"}">'
        f'<span class="settings-badge-icon">{_svg("circle_dot", size=10, color="#1E5F91" if active_count else "#94a3b8")}</span>'
        f'<span>{active_count} bound</span></span>'
    )

    with st.container(border=True):
        _section_header(icon="radio", title="Channel bindings", badge_html=badge_html)
        st.caption(
            "Issue an auth code (Stage A § B7), DM the tenant's bot with `/start <code>`, "
            "and the polling worker binds the identity here."
        )

        _rbac_lockout_banner(
            can_issue,
            permission="channel_auth_code:issue",
            action_label="Issue code",
        )

        # Issue row
        issue_cols = st.columns([2, 1, 1])
        with issue_cols[0]:
            kind = st.selectbox(
                "Channel", _CHANNEL_KINDS, index=0, key="auth-code-kind",
            )
        with issue_cols[1]:
            ttl = st.number_input(
                "TTL (min)", min_value=1, max_value=1440, value=15, key="auth-code-ttl",
            )
        with issue_cols[2]:
            st.markdown('<div class="settings-issue-spacer"></div>', unsafe_allow_html=True)
            if st.button(
                "Issue code",
                key="auth-code-issue",
                disabled=not can_issue.allowed,
                use_container_width=True,
                type="primary",
                help=None if can_issue.allowed else f"channel_auth_code:issue required (your role: {can_issue.role})",
            ):
                try:
                    resp = api.issue_channel_auth_code(channel_kind=kind, ttl_minutes=int(ttl))
                    st.success(f"Code: `{resp['code']}` · expires {resp['expires_at']}")
                    st.code(resp["instructions"], language="text")
                except APIError as err:
                    st.error(f"{err.status_code} — {err.detail}")

        st.markdown('<hr class="settings-sep" />', unsafe_allow_html=True)

        st.markdown(
            '<div class="settings-subhead">Bound identities</div>',
            unsafe_allow_html=True,
        )
        if not identities:
            st.caption("No identities bound yet for this tenant.")
            return
        for ident in identities:
            cols = st.columns([3, 1, 1, 1])
            with cols[0]:
                st.markdown(
                    f'<div class="settings-identity-row">'
                    f'<code>{ident["channel_kind"]}</code> · '
                    f'<code>{ident["external_id"]}</code> → user '
                    f'<code>{ident["user_id"][:8]}…</code>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with cols[1]:
                if ident["status"] == "active":
                    st.markdown(
                        f'<span class="settings-badge settings-badge-set">'
                        f'<span class="settings-badge-icon">{_svg("circle_dot", size=10, color="#1E5F91")}</span>'
                        f'<span>active</span></span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<span class="settings-badge settings-badge-neutral"><span>revoked</span></span>',
                        unsafe_allow_html=True,
                    )
            with cols[2]:
                if ident.get("last_seen_at"):
                    st.caption(f"last seen: {ident['last_seen_at']}")
            with cols[3]:
                if ident["status"] == "active":
                    if st.button(
                        "Revoke",
                        key=f"rev-{ident['id']}",
                        disabled=not can_revoke.allowed,
                        use_container_width=True,
                        help=None if can_revoke.allowed else f"channel_identity:revoke required (your role: {can_revoke.role})",
                    ):
                        try:
                            api.revoke_channel_identity(ident["id"])
                            st.success("Revoked.")
                            st.rerun()
                        except APIError as err:
                            st.error(f"{err.detail}")


# ── CSS ──────────────────────────────────────────────────────────────


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --set-border: #e5e7eb;
          --set-border-strong: #cbd5e1;
          --set-text: #111827;
          --set-muted: #6b7280;
          --set-muted-soft: #94a3b8;
          --set-primary: #1E5F91;
          --set-primary-soft: rgba(30, 95, 145, 0.08);
          --set-warn: #B45309;
          --set-warn-soft: rgba(180, 83, 9, 0.08);
          --set-surface: #ffffff;
          --set-surface-alt: #f8fafc;
        }

        /* Page heading — IWO2 settings.tsx h1 + p */
        .settings-page-title {
          font-size: 1.4rem;
          font-weight: 600;
          color: var(--set-text);
          letter-spacing: -0.01em;
          margin: 0;
        }
        .settings-page-subtitle {
          font-size: 0.86rem;
          color: var(--set-muted);
          margin: 0.3rem 0 1.2rem 0;
          line-height: 1.5;
        }

        /* Cards — every st.container(border=True) on this page is a
           settings card. Tight, IWO2-shaped. */
        div[data-testid="stVerticalBlockBorderWrapper"] {
          border: 1px solid var(--set-border) !important;
          border-radius: 6px !important;
          background: var(--set-surface) !important;
          padding: 1rem 1.1rem 1rem 1.1rem !important;
          margin-bottom: 0.85rem;
          transition: border-color 150ms ease, box-shadow 150ms ease;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {
          border-color: var(--set-border-strong);
        }

        /* Card header — icon+title left, badges right (IWO2 CardHeader idiom) */
        .settings-card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 0.75rem;
          flex-wrap: wrap;
          margin-bottom: 0.4rem;
          padding-bottom: 0.55rem;
          border-bottom: 1px solid var(--set-border);
        }
        .settings-card-title {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.9rem;
          font-weight: 600;
          color: var(--set-text);
        }
        .settings-card-icon {
          display: inline-flex;
          color: var(--set-primary);
          line-height: 0;
        }
        .settings-card-icon svg { display: block; }

        /* Status badges — IWO2 Badge variant idiom */
        .settings-card-badges {
          display: inline-flex;
          align-items: center;
          gap: 0.3rem;
        }
        .settings-badge {
          display: inline-flex;
          align-items: center;
          gap: 0.3rem;
          padding: 0.18rem 0.5rem;
          border-radius: 4px;
          font-size: 0.7rem;
          font-weight: 500;
          line-height: 1;
        }
        .settings-badge-set {
          background: var(--set-primary-soft);
          color: var(--set-primary);
          border: 1px solid var(--set-primary-soft);
        }
        .settings-badge-missing {
          background: var(--set-warn-soft);
          color: var(--set-warn);
          border: 1px solid var(--set-warn-soft);
        }
        .settings-badge-neutral {
          background: #f1f5f9;
          color: var(--set-muted);
          border: 1px solid var(--set-border);
        }
        .settings-badge-icon {
          display: inline-flex;
          line-height: 0;
        }
        .settings-badge-icon svg { display: block; }

        /* Provider availability chips */
        .settings-pchip-row {
          display: flex;
          gap: 0.35rem;
          flex-wrap: wrap;
          margin: 0.4rem 0 0.65rem 0;
        }
        .settings-pchip {
          display: inline-flex;
          align-items: center;
          gap: 0.3rem;
          padding: 0.2rem 0.55rem;
          border-radius: 4px;
          font-size: 0.7rem;
          font-weight: 500;
          color: var(--set-muted);
          background: #f8fafc;
          border: 1px solid var(--set-border);
        }
        .settings-pchip-set {
          color: var(--set-primary);
          background: var(--set-primary-soft);
          border-color: rgba(30, 95, 145, 0.2);
        }
        .settings-pchip svg { display: block; }

        /* Bordered enable-toggle row */
        .settings-toggle-text {
          padding: 0.65rem 0.7rem 0.5rem 0.1rem;
        }
        .settings-toggle-title {
          font-size: 0.85rem;
          font-weight: 600;
          color: var(--set-text);
        }
        .settings-toggle-sub {
          font-size: 0.74rem;
          color: var(--set-muted);
          line-height: 1.4;
          margin-top: 0.15rem;
        }

        /* IWO2-style API-key info bar (muted background, key icon, copy) */
        .settings-keybar {
          display: flex;
          align-items: flex-start;
          gap: 0.55rem;
          padding: 0.65rem 0.75rem;
          border-radius: 6px;
          background: #f1f5f9;
          margin: 0.5rem 0 0.5rem 0;
        }
        .settings-keybar-icon {
          color: var(--set-muted);
          flex-shrink: 0;
          line-height: 0;
          margin-top: 0.1rem;
        }
        .settings-keybar-icon svg { display: block; }
        .settings-keybar-body {
          font-size: 0.74rem;
          color: var(--set-muted);
          line-height: 1.45;
        }
        .settings-keybar-body code {
          font-family: ui-monospace, SFMono-Regular, monospace;
          color: var(--set-text);
          background: var(--set-surface);
          padding: 0.05rem 0.3rem;
          border-radius: 3px;
          border: 1px solid var(--set-border);
          font-size: 0.74rem;
        }

        /* Section divider line inside a card */
        .settings-sep {
          border: 0;
          border-top: 1px solid var(--set-border);
          margin: 0.85rem 0 0.7rem 0;
        }

        /* RBAC lockout banner — explains why action buttons are
           disabled instead of leaving them mystery-grey. */
        .settings-rbac-banner {
          display: flex;
          align-items: flex-start;
          gap: 0.5rem;
          padding: 0.55rem 0.75rem;
          border-radius: 6px;
          background: var(--set-warn-soft);
          border: 1px solid rgba(180, 83, 9, 0.2);
          margin: 0.45rem 0 0.65rem 0;
        }
        .settings-rbac-icon {
          color: var(--set-warn);
          flex-shrink: 0;
          line-height: 0;
          margin-top: 0.1rem;
        }
        .settings-rbac-icon svg { display: block; }
        .settings-rbac-body {
          font-size: 0.74rem;
          color: var(--set-warn);
          line-height: 1.5;
        }
        .settings-rbac-body strong {
          font-weight: 600;
        }
        .settings-rbac-body code {
          font-family: ui-monospace, SFMono-Regular, monospace;
          background: rgba(180, 83, 9, 0.1);
          color: var(--set-warn);
          padding: 0.05rem 0.3rem;
          border-radius: 3px;
          font-size: 0.74rem;
        }

        .settings-subhead {
          font-size: 0.82rem;
          font-weight: 600;
          color: var(--set-text);
          margin: 0.45rem 0 0.4rem 0;
        }

        /* Persona rows — compact list */
        .settings-persona-scope {
          font-size: 0.72rem;
          color: var(--set-muted);
          margin: 0.45rem 0 0.2rem 0;
          letter-spacing: 0.01em;
        }
        .settings-persona-scope code {
          color: var(--set-text);
          font-size: 0.72rem;
        }
        .settings-persona-row {
          display: flex;
          align-items: center;
          gap: 0.6rem;
          padding: 0.3rem 0.5rem;
          border: 1px solid var(--set-border);
          border-radius: 4px;
          background: var(--set-surface-alt);
          margin-bottom: 0.25rem;
          font-size: 0.78rem;
        }
        .settings-persona-name {
          font-weight: 600;
          color: var(--set-text);
        }
        .settings-persona-key {
          font-family: ui-monospace, SFMono-Regular, monospace;
          color: var(--set-muted);
          font-size: 0.72rem;
        }
        .settings-persona-status {
          font-size: 0.7rem;
          color: var(--set-muted-soft);
          margin-left: auto;
        }

        /* Identity rows */
        .settings-identity-row {
          font-size: 0.78rem;
          color: var(--set-text);
          padding: 0.2rem 0;
        }
        .settings-identity-row code {
          font-family: ui-monospace, SFMono-Regular, monospace;
          color: var(--set-text);
          background: #f1f5f9;
          padding: 0.05rem 0.3rem;
          border-radius: 3px;
          font-size: 0.74rem;
        }

        .settings-issue-spacer {
          height: 1.65rem;  /* aligns "Issue code" button with the inputs above */
        }

        /* Buttons inside settings cards — keep IWO2 compact action row */
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
          background: var(--set-primary);
          color: #ffffff;
          border: 1px solid var(--set-primary);
          font-weight: 500;
          font-size: 0.84rem;
          border-radius: 4px;
          min-height: 2.1rem;
          box-shadow: none;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="primary"]:hover,
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
          background: #174c75;
          border-color: #174c75;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="secondary"],
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stFormSubmitButton"] > button[kind="secondary"] {
          background: var(--set-surface);
          color: var(--set-text);
          border: 1px solid var(--set-border);
          font-weight: 500;
          font-size: 0.84rem;
          border-radius: 4px;
          min-height: 2.1rem;
          box-shadow: none;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="secondary"]:hover,
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stFormSubmitButton"] > button[kind="secondary"]:hover {
          border-color: var(--set-primary);
          color: var(--set-primary);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ── Page ─────────────────────────────────────────────────────────────


def main() -> None:
    _inject_css()

    api = page_requires_api()
    if api is None:
        return

    # IWO2 settings.tsx layout: max-w-3xl mx-auto. Streamlit can't natively
    # do that without st.set_page_config — approximate via a 1:5:1 column
    # split that gives the body ~71% of the viewport width.
    _, body, _ = st.columns([1, 5, 1])
    with body:
        st.markdown('<div class="settings-page-title">Aiden Configuration</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="settings-page-subtitle">Configure the LLM that powers Aiden\'s orchestration decisions, '
            'plus per-tenant ceilings, persona library, and channel bindings for this tenant.</div>',
            unsafe_allow_html=True,
        )

        _section_aiden_config(api)
        _section_tenant_ceiling(api)
        _section_persona_library(api)
        _section_channels(api)


main()
