"""Sub-Agents — Pre-Beta β.6 CRUD parity v1.

Browser-side management of `llm_configs` rows: edit provider/model/
base URL/system prompt/enabled, create new sub-agent rows, soft-delete
(disable) existing rows. Connection-test still works after edits.

The IWO2 modal carries Tool Access + Tool History; those are explicitly
deferred to MegaLoop Beta per ADR-024 + the Pre-Beta directive.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from api_client import APIError
from shell import page_requires_api


_ROLE_LABELS = {
    "aiden_tier_1": "Aiden (Tier 1)",
    "pm_tier_15": "PM (Tier 1.5)",
    "mark_tier_2": "Mark (content)",
    "tom_tier_2": "Tom (decks)",
    "hank_tier_2": "Hank (web)",
    "paul_tier_2": "Paul (deployment)",
}

_PROVIDER_OPTIONS = ["groq", "openrouter", "openai", "anthropic"]


def _credential_chip(state: str, env_name: str | None) -> str:
    if state == "set":
        return f"🟢 ENV `{env_name}` set"
    if state == "missing":
        return f"⛔ ENV `{env_name}` not set"
    return "⛔ credential_ref malformed"


def _render_edit_form(
    api,
    cfg: dict,
    can_admin: bool,
    *,
    form_key: str,
) -> None:
    with st.form(key=form_key, clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            display_name = st.text_input(
                "Display name",
                value=cfg["display_name"],
                key=f"{form_key}-name",
            )
            provider = st.selectbox(
                "Provider",
                _PROVIDER_OPTIONS,
                index=(
                    _PROVIDER_OPTIONS.index(cfg["provider"])
                    if cfg["provider"] in _PROVIDER_OPTIONS
                    else 0
                ),
                key=f"{form_key}-prov",
            )
            model = st.text_input(
                "Model",
                value=cfg["model"],
                key=f"{form_key}-model",
            )
        with col2:
            enabled = st.toggle(
                "Enabled",
                value=cfg["enabled"],
                key=f"{form_key}-enabled",
            )
            base_url = st.text_input(
                "Base URL (optional)",
                value=cfg.get("base_url") or "",
                key=f"{form_key}-base",
            )
            credential_ref = st.text_input(
                "Credential ref (e.g. credential_ref:env:GROQ_API_KEY)",
                value="",
                placeholder="leave blank to keep existing",
                key=f"{form_key}-credref",
            )

        description = st.text_area(
            "Description",
            value=cfg.get("description") or "",
            key=f"{form_key}-desc",
            height=70,
        )

        # Beta-2 phase 0.3.1 — pre-load the actual prompt body via the
        # writer-gated /prompt endpoint so operators can see + edit
        # instead of blind-overwriting.
        current_prompt = ""
        if can_admin:
            try:
                pr = api.get_llm_config_prompt(cfg["id"])
                current_prompt = pr.get("system_prompt") or ""
            except APIError as err:
                st.warning(
                    f"Could not load current prompt: {err.status_code} — {err.detail}"
                )

        st.markdown(
            f"**System Prompt** &nbsp;·&nbsp; "
            f"<span style='color:#6B7280; font-size:0.8rem;'>"
            f"{len(current_prompt)} chars currently stored</span>",
            unsafe_allow_html=True,
        )
        prompt_action = st.radio(
            "What do you want to do with the system prompt?",
            options=["Keep unchanged", "Replace with new prompt", "Clear (reset to default)"],
            index=0,
            horizontal=True,
            key=f"{form_key}-prompt-action",
            label_visibility="collapsed",
        )
        system_prompt = st.text_area(
            "System Prompt",
            value=current_prompt,
            key=f"{form_key}-prompt",
            height=180,
            disabled=prompt_action != "Replace with new prompt",
            label_visibility="collapsed",
        )
        change_reason = st.text_input(
            "Change reason (optional, recorded in version history)",
            value="",
            key=f"{form_key}-reason",
            placeholder="e.g. 'Sharper deck-builder voice for Klear pitches'",
        )

        save = st.form_submit_button(
            "Save changes",
            type="primary",
            disabled=not can_admin,
        )
        if save:
            patch: dict[str, Any] = {
                "display_name": display_name,
                "description": description or None,
                "provider": provider,
                "model": model,
                "base_url": base_url or None,
                "enabled": enabled,
            }
            if credential_ref.strip():
                patch["credential_ref"] = credential_ref.strip()
            # Beta-2 phase 0.3.2 tri-state contract.
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
                api.update_llm_config(cfg["id"], **patch)
                st.success("Saved. New version row written for rollback.")
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")


def _render_history_tab(api, cfg: dict, can_admin: bool) -> None:  # noqa: ANN001
    """Beta-2 phase 0.3.3 — version list + rollback button per row.

    Shows newest-first version history. Each version row carries
    change_action / changed_fields / change_reason / actor / timestamp.
    Rollback button (writer-gated) writes a new mutation that restores
    the chosen historical state.
    """
    try:
        versions = api.list_llm_config_versions(cfg["id"], limit=50)
    except APIError as err:
        st.error(f"Could not load history: {err.status_code} — {err.detail}")
        return

    if not versions:
        st.caption("No history yet. Edit the prompt to create a version.")
        return

    st.caption(
        f"{len(versions)} version(s). Newest first. Rollback writes a new "
        f"version row pointing at the chosen historical snapshot."
    )

    for v in versions:
        v_num = v["version_number"]
        action = v["change_action"]
        action_emoji = {
            "initial": "📌",
            "create": "✨",
            "update": "✏️",
            "rollback": "↩️",
        }.get(action, "•")
        prompt_chip = "📝" if v["has_system_prompt"] else "—"
        cols = st.columns([3, 1])
        with cols[0]:
            st.markdown(
                f"**{action_emoji} v{v_num} — {action}** &nbsp;·&nbsp; "
                f"`{v['provider']}/{v['model']}` &nbsp;·&nbsp; "
                f"prompt {prompt_chip} &nbsp;·&nbsp; "
                f"<span style='color:#6B7280; font-size:0.8rem;'>"
                f"{v['created_at'][:19]}</span>",
                unsafe_allow_html=True,
            )
            if v.get("change_reason"):
                st.caption(f"_Reason: {v['change_reason']}_")
            if v.get("changed_fields"):
                st.caption(
                    f"Changed fields: `{', '.join(v['changed_fields'])}`"
                )
        with cols[1]:
            if st.button(
                "Rollback to this",
                key=f"rb-{cfg['id']}-{v['id']}",
                disabled=not can_admin or action == "initial" and v_num == 1 and len(versions) == 1,
                use_container_width=True,
            ):
                try:
                    api.rollback_llm_config(
                        cfg["id"],
                        version_id=v["id"],
                        change_reason=f"Rolled back to v{v_num}",
                    )
                    st.success(f"Rolled back to v{v_num}. New version row written.")
                    st.rerun()
                except APIError as err:
                    st.error(f"❌ {err.status_code} — {err.detail}")
        st.markdown("---")


def _render_new_form(api, can_admin: bool) -> None:
    with st.form(key="new-subagent", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            agent_role = st.text_input(
                "Agent role key",
                placeholder="e.g. tom_tier_2",
                help="lowercase + underscores only",
            )
            display_name = st.text_input(
                "Display name", placeholder="Tom (decks)"
            )
            provider = st.selectbox("Provider", _PROVIDER_OPTIONS)
            model = st.text_input(
                "Model", placeholder="openai/gpt-oss-120b"
            )
        with col2:
            base_url = st.text_input(
                "Base URL (optional)", placeholder="leave blank for provider default"
            )
            credential_ref = st.text_input(
                "Credential ref",
                value="credential_ref:env:GROQ_API_KEY",
            )
            enabled = st.toggle("Enabled", value=True)
        description = st.text_area("Description", height=70)
        system_prompt = st.text_area(
            "System prompt (optional)", height=140
        )
        submit = st.form_submit_button(
            "Create sub-agent", type="primary", disabled=not can_admin
        )
        if submit:
            if not agent_role or not display_name or not model:
                st.warning("agent_role, display_name, and model are required.")
                return
            try:
                api.create_llm_config(
                    agent_role=agent_role,
                    display_name=display_name,
                    description=description or None,
                    provider=provider,
                    model=model,
                    base_url=base_url or None,
                    credential_ref=credential_ref,
                    system_prompt=system_prompt or None,
                    enabled=enabled,
                )
                st.success(f"Created {agent_role}.")
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Sub-Agents</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Tier-1 / Tier-1.5 / Tier-2 LLM configs. Edit provider, model,
          base URL, system prompt, enabled. New rows can be added below.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        configs = api.list_llm_configs()
        # Beta-2 phase 0.3.5 RBAC fix — gate on llm_config:write (CODEX
        # 2026-05-01 finding 5). Connection-test gates on the same.
        can_admin = api.check_permission("llm_config:write")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not can_admin.allowed:
        st.info(
            f"Your role `{can_admin.role}` lacks `llm_config:write`. "
            f"Edit + create + connection-test are disabled; read remains "
            f"available."
        )

    if not configs:
        st.info(
            "No LLM configs for this tenant yet — use the New Sub-Agent "
            "form below to create the first one."
        )

    for cfg in sorted(configs, key=lambda c: c["agent_role"]):
        label = _ROLE_LABELS.get(cfg["agent_role"], cfg["agent_role"])
        chip = "🟢" if cfg["enabled"] else "⚪"
        cred_chip = _credential_chip(
            cfg["credential_state"], cfg.get("env_var_name")
        )
        with st.expander(
            f"{chip} **{cfg['display_name']}** "
            f"({cfg['agent_role']}) — `{cfg['provider']}` / `{cfg['model']}`",
            expanded=False,
        ):
            st.caption(f"id `{cfg['id']}` · {cred_chip}")
            if cfg.get("description"):
                st.caption(cfg["description"])

            tabs = st.tabs(["Edit", "History", "Test connection", "Disable"])
            with tabs[0]:
                _render_edit_form(
                    api,
                    cfg,
                    can_admin.allowed,
                    form_key=f"edit-{cfg['id']}",
                )
            with tabs[1]:
                _render_history_tab(api, cfg, can_admin.allowed)
            with tabs[2]:
                if st.button(
                    "Run connection test",
                    key=f"test-{cfg['id']}",
                    disabled=not can_admin.allowed,
                ):
                    with st.spinner("calling provider…"):
                        try:
                            r = api.test_llm(
                                agent_role=cfg["agent_role"]
                            )
                        except APIError as err:
                            st.error(
                                f"❌ {err.status_code} — {err.detail}"
                            )
                            r = None
                    if r:
                        if r.get("ok"):
                            st.success(
                                f"✅ {r['provider']}/{r['model']} · "
                                f"{r['latency_ms']}ms"
                            )
                            if r.get("sample"):
                                st.caption(f"Sample: {r['sample']}")
                        else:
                            st.warning(f"⚠️ {r.get('error')}")
            with tabs[3]:
                if cfg["enabled"]:
                    if st.button(
                        f"Disable {cfg['display_name']}",
                        key=f"del-{cfg['id']}",
                        disabled=not can_admin.allowed,
                    ):
                        try:
                            api.delete_llm_config(cfg["id"])
                            st.success("Disabled.")
                            st.rerun()
                        except APIError as err:
                            st.error(f"❌ {err.detail}")
                else:
                    st.caption(
                        "Already disabled. Re-enable via the Edit tab."
                    )

    st.divider()
    with st.expander("➕ New sub-agent", expanded=False):
        _render_new_form(api, can_admin.allowed)


main()
