"""Sub-Agents — Loop Eta phase 1 Worker D rebuild toward IWO2 parity.

What changed from Pre-Beta β.6:
  * Card-grid layout that scales to all 11 IWO2-parity sub-agents
    (1 aiden_tier_1 + 1 pm_tier_15 + 6 imported Tier-2 roles + 3
    parity approximations).
  * Provenance badge per card (extracted_from_iwo2_live = green,
    extracted_from_iwo2_static = blue, authored_parity_approximation
    = amber, authored_net_new = violet, otherwise "unknown").
  * Tool Access tab with the global tool_catalog rendered as a
    checkbox grid; each toggle hits PUT /llm/configs/{id}/tools/{key}.
  * Runtime Tools tab — chips listing currently-runnable + assigned
    + enabled tools (mirrors IWO2 RuntimeToolsSummary).
  * Tool History tab — real per-agent runtime tool-call history backed
    by GET /llm/configs/{id}/tool_history.
  * RBAC banner per write surface (llm_config:write for prompt/connection
    edits, sub_agent_tool:assign for Tool Access toggles).

Preserved from Pre-Beta β.6:
  * Persona / system prompt editor with tri-state contract.
  * Provider/model/base_url/credential_ref edit form.
  * Version history + rollback button.
  * Connection test button.
  * Soft-delete (Disable) button.
  * "New sub-agent" form below the grid.

Architectural locks honoured:
  * Consumes the locked APIs only — the 3 new helpers from Worker C
    plus existing `list_configs`, `update_config`, `get_config_prompt`,
    `list_versions`, `rollback_config`, `test_llm`, `delete_config`,
    `create_config`. No speculative endpoints.
  * No backend / schema / seed mutations — UI only.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from api_client import APIError
from model_picker import render_catalog_controls, render_model_picker
from shell import page_requires_api


_ROLE_LABELS = {
    "aiden_tier_1": "Aiden (Tier 1)",
    "pm_tier_15": "PM (Tier 1.5)",
    "mark_tier_2": "Mark (content)",
    "tom_tier_2": "Tom (decks)",
    "hank_tier_2": "Hank (web)",
    "paul_tier_2": "Paul (deployment)",
    "jamie_tier_2": "Jamie (EA / scheduling)",
    "nyx_tier_2": "Nyx (security / compliance)",
    "polaris_tier_2": "Polaris (ops / SLA)",
    "darla_tier_2": "Darla (design)",
    "sop_master_tier_2": "SOP Master (process)",
}

_PROVIDER_OPTIONS = ["groq", "openrouter", "openai", "anthropic"]

# Providers present in the dropdown that the runtime cannot actually
# call — `GET /llm/providers` reports `callable_in_phase_9_3: false`.
# Selecting one saves cleanly and then fails at invoke time, so the form
# warns rather than silently accepting it.
_NON_CALLABLE_PROVIDERS = {"anthropic"}

# Conventional credential env var per provider. Switching provider
# without also switching the credential leaves the config pointed at
# another provider's key; the save succeeds and every later invoke
# returns HTTP 401 "Invalid API Key" — which reads as a dead key, not a
# mis-wired config. Hit live on Darla (2026-09-05) the first time the
# new model picker made switching provider a one-click affair.
_PROVIDER_ENV_VAR = {
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _expected_credential_ref(provider: str) -> str:
    env = _PROVIDER_ENV_VAR.get(provider)
    return f"credential_ref:env:{env}" if env else ""


# ── small helpers ─────────────────────────────────────────────────────


def _credential_chip(state: str, env_name: str | None) -> str:
    if state == "set":
        return f"🟢 ENV `{env_name}` set"
    if state == "missing":
        return f"⛔ ENV `{env_name}` not set"
    return "⛔ credential_ref malformed"


def _provenance_label(value: str) -> tuple[str, str, str]:
    """Return (display_text, bg_color, fg_color) for the badge."""
    if value == "extracted_from_iwo2_live":
        return ("IWO2 live import", "#DCFCE7", "#166534")
    if value == "extracted_from_iwo2_static":
        return ("IWO2 static port", "#DBEAFE", "#1E40AF")
    if value == "authored_parity_approximation":
        return ("parity approximation", "#FEF3C7", "#92400E")
    if value == "authored_net_new":
        return ("net new", "#EDE9FE", "#5B21B6")
    return ("unknown provenance", "#E5E7EB", "#374151")


def _provenance_badge_html(value: str) -> str:
    text, bg, fg = _provenance_label(value)
    return (
        f'<span style="display:inline-block; padding:2px 8px; '
        f'border-radius:9999px; background:{bg}; color:{fg}; '
        f'font-size:0.72rem; font-weight:600;">{text}</span>'
    )


def _provenance_for_config(cfg: dict[str, Any]) -> str:
    """Best-effort provenance read.

    The current `/llm/configs` response does not surface the
    `metadata.prompt_provenance` column (Pre-Beta β.6 schema). We read
    it defensively in case the API evolves later, and otherwise return
    "unknown" — exactly as the loop spec requires.
    """
    meta = cfg.get("metadata") or {}
    if isinstance(meta, dict):
        prov = meta.get("prompt_provenance")
        if isinstance(prov, str) and prov:
            return prov
    return "unknown"


def _rbac_banner(decision, *, permission: str, action_label: str) -> None:  # noqa: ANN001
    """Render an inline amber banner explaining why the surface is
    locked. Mirrors `aiden_settings._rbac_lockout_banner` minus its
    custom CSS so this view stays self-contained."""
    if decision.allowed:
        return
    st.markdown(
        f"""
        <div style="
          background:#FEF3C7;
          border:1px solid #F59E0B;
          border-radius:6px;
          padding:8px 12px;
          font-size:0.85rem;
          color:#92400E;
          margin:4px 0 12px 0;
        ">
          <strong>{action_label} disabled</strong> — your role
          <code>{decision.role}</code> does not include
          <code>{permission}</code>. Sign in as a role that carries
          this permission to make changes.
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── card header (1) ───────────────────────────────────────────────────


def _render_card_header(cfg: dict[str, Any]) -> None:
    """Section 1 — IWO2-style card header.

    Display name, role chip, provider/model chip, status chip,
    credential chip, provenance badge.
    """
    label = _ROLE_LABELS.get(cfg["agent_role"], cfg["agent_role"])
    status_chip = (
        '<span style="background:#DCFCE7; color:#166534; padding:2px 8px; '
        'border-radius:9999px; font-size:0.72rem; font-weight:600;">'
        'enabled</span>'
        if cfg["enabled"]
        else '<span style="background:#E5E7EB; color:#374151; padding:2px 8px; '
        'border-radius:9999px; font-size:0.72rem; font-weight:600;">disabled</span>'
    )
    provider_chip = (
        f'<span style="background:#CFFAFE; color:#155E75; padding:2px 8px; '
        f'border-radius:9999px; font-size:0.72rem; font-weight:600;">'
        f'{cfg["provider"]} / {cfg["model"]}</span>'
    )
    role_chip = (
        f'<span style="background:#F3F4FA; color:#374151; padding:2px 8px; '
        f'border-radius:9999px; font-size:0.72rem; font-weight:600;">'
        f'{cfg["agent_role"]}</span>'
    )
    prov_chip = _provenance_badge_html(_provenance_for_config(cfg))
    cred_state = cfg.get("credential_state", "missing")
    env_name = cfg.get("env_var_name")
    cred_chip_color = (
        ("#DCFCE7", "#166534")
        if cred_state == "set"
        else ("#FEE2E2", "#991B1B")
    )
    cred_text = (
        f"ENV {env_name} set"
        if cred_state == "set"
        else f"ENV {env_name or '?'} {cred_state}"
    )
    cred_chip = (
        f'<span style="background:{cred_chip_color[0]}; color:{cred_chip_color[1]}; '
        f'padding:2px 8px; border-radius:9999px; font-size:0.72rem; font-weight:600;">'
        f'{cred_text}</span>'
    )

    st.markdown(
        f"""
        <div style="
          display:flex; flex-direction:column; gap:6px;
          padding:4px 0 6px 0;
        ">
          <div style="font-size:1.05rem; font-weight:700;">
            🤖 {cfg["display_name"]}
            <span style="color:#6B7280; font-weight:500; font-size:0.84rem;">
              — {label}
            </span>
          </div>
          <div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">
            {status_chip} {role_chip} {provider_chip} {cred_chip} {prov_chip}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if cfg.get("description"):
        st.caption(cfg["description"])
    st.caption(f"id `{cfg['id']}`")


# ── persona / connection editor (2 + 3) ───────────────────────────────


def _render_edit_form(
    api,  # noqa: ANN001
    cfg: dict[str, Any],
    *,
    can_admin: bool,
    form_key: str,
) -> None:
    """Sections 2 + 3 — persona / system prompt + LLM connection.

    Combined under a single "Edit" tab to keep the Streamlit form
    submission semantics intact. Persona text area sits up top; the
    provider/model/base_url/credential_ref controls live below.
    """
    # Pre-load actual prompt body via the writer-gated /prompt endpoint
    # so operators see what's there before they rewrite it.
    current_prompt = ""
    if can_admin:
        try:
            pr = api.get_llm_config_prompt(cfg["id"])
            current_prompt = pr.get("system_prompt") or ""
        except APIError as err:
            st.warning(
                f"Could not load current prompt: {err.status_code} — {err.detail}"
            )

    st.markdown("**Section 3a — Provider & model**")
    pcol, _ = st.columns([1, 2])
    with pcol:
        provider = st.selectbox(
            "Provider",
            _PROVIDER_OPTIONS,
            index=(
                _PROVIDER_OPTIONS.index(cfg["provider"])
                if cfg["provider"] in _PROVIDER_OPTIONS
                else 0
            ),
            key=f"{form_key}-prov",
            disabled=not can_admin,
        )
    if provider in _NON_CALLABLE_PROVIDERS:
        st.warning(
            f"`{provider}` is not callable in this runtime "
            "(`GET /llm/providers` reports callable=false). A config saved "
            "against it will store cleanly but the agent will not run."
        )
    model = render_model_picker(
        api,
        provider=provider,
        current_model=cfg["model"],
        key_prefix=f"{form_key}-mp",
        disabled=not can_admin,
        base_url=cfg.get("base_url") or "",
    )
    render_catalog_controls(
        api, provider=provider, key_prefix=f"{form_key}-mp", disabled=not can_admin
    )
    provider_switched = provider != cfg["provider"]
    if model != cfg["model"] or provider_switched:
        st.info(
            f"Pending change: `{cfg['provider']}/{cfg['model']}` → "
            f"`{provider}/{model}` — not saved until you press "
            "**Save changes** below."
        )
    if provider_switched:
        st.warning(
            f"**Provider changed to `{provider}` — its credential must change too.** "
            f"This config currently authenticates with "
            f"`{cfg.get('env_var_name') or 'its existing key'}`. Sending that to "
            f"`{provider}` returns HTTP 401 *Invalid API Key*. The Credential ref "
            f"field below has been pre-filled with "
            f"`{_expected_credential_ref(provider)}` — clear it only if this "
            f"deployment names its key something else."
        )
    st.divider()

    with st.form(key=form_key, clear_on_submit=False):
        st.markdown("**Section 2 — Persona / system prompt**")
        st.markdown(
            f"<div style='color:#6B7280; font-size:0.78rem; margin:-6px 0 6px 0;'>"
            f"{len(current_prompt)} chars currently stored.</div>",
            unsafe_allow_html=True,
        )
        prompt_action = st.radio(
            "Prompt mutation",
            options=[
                "Keep unchanged",
                "Replace with new prompt",
                "Clear (reset to default)",
            ],
            index=0,
            horizontal=True,
            key=f"{form_key}-prompt-action",
        )
        system_prompt = st.text_area(
            "System prompt",
            value=current_prompt,
            key=f"{form_key}-prompt",
            height=200,
            disabled=prompt_action != "Replace with new prompt",
        )
        change_reason = st.text_input(
            "Change reason (recorded on the version row)",
            value="",
            key=f"{form_key}-reason",
            placeholder="e.g. 'Sharper deck-builder voice for Klear pitches'",
        )

        st.divider()
        st.markdown("**Section 3b — Connection details**")
        col1, col2 = st.columns(2)
        with col1:
            display_name = st.text_input(
                "Display name",
                value=cfg["display_name"],
                key=f"{form_key}-name",
            )
            st.caption(
                f"Provider / model — set above: `{provider}` / `{model}`"
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
                value=(
                    _expected_credential_ref(provider)
                    if provider_switched
                    else ""
                ),
                placeholder="leave blank to keep existing",
                key=f"{form_key}-credref-{provider}",
                help=(
                    "Blank keeps the stored credential. Pre-filled "
                    "automatically when you switch provider, because the "
                    "old provider's key will 401 against the new one."
                ),
            )
        description = st.text_area(
            "Description",
            value=cfg.get("description") or "",
            key=f"{form_key}-desc",
            height=70,
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


# ── tool access (4) ───────────────────────────────────────────────────


def _render_tool_access_tab(
    api,  # noqa: ANN001
    cfg: dict[str, Any],
    *,
    can_assign: bool,
) -> None:
    """Section 4 — Tool Access checkbox grid.

    GET /llm/configs/{id}/tools returns the catalog joined with the
    sub_agent_tools assignment state (`assigned`, `enabled`). Toggling
    a checkbox PUTs the new state. Tools whose `runtime_status` is not
    `runnable` (i.e. skill_only, mcp_pending) are visible but rendered
    disabled with a tooltip.
    """
    try:
        bundle = api.get_sub_agent_tools(cfg["id"])
    except APIError as err:
        st.error(f"Could not load tools: {err.status_code} — {err.detail}")
        return

    tools = bundle.get("tools", [])
    if not tools:
        st.caption(
            "Global tool catalog is empty (or every row is disabled). "
            "Seed the catalog before assigning."
        )
        return

    enabled_count = sum(1 for t in tools if t.get("enabled"))
    runnable_count = sum(
        1 for t in tools if t.get("runtime_status") == "runnable"
    )
    st.caption(
        f"{enabled_count} of {len(tools)} catalog rows enabled. "
        f"{runnable_count} are runtime-runnable."
    )

    # Group by category for readability — matches IWO2 visual chunking.
    by_category: dict[str, list[dict[str, Any]]] = {}
    for tool in tools:
        by_category.setdefault(tool.get("category", "other"), []).append(tool)

    for category, rows in sorted(by_category.items()):
        st.markdown(f"**{category}**")
        for tool in rows:
            tool_key = tool["tool_key"]
            display = tool.get("display_name") or tool_key
            runtime_status = tool.get("runtime_status", "runnable")
            is_runnable = runtime_status == "runnable"
            currently_enabled = bool(tool.get("enabled"))
            is_assigned = bool(tool.get("assigned"))
            iwo2_origin = tool.get("iwo2_origin")
            default_tier = tool.get("default_tier")

            cols = st.columns([0.07, 0.55, 0.38])
            with cols[0]:
                # Streamlit checkboxes don't support a true tooltip on
                # disabled checkboxes; use the `help=` arg.
                disabled_reason = None
                if not can_assign:
                    disabled_reason = (
                        "sub_agent_tool:assign required to toggle"
                    )
                elif not is_runnable:
                    disabled_reason = (
                        f"runtime_status={runtime_status} — not runnable"
                    )
                new_value = st.checkbox(
                    "",  # label rendered next column for layout control
                    value=currently_enabled,
                    key=f"tool-{cfg['id']}-{tool_key}",
                    disabled=(not can_assign) or (not is_runnable),
                    label_visibility="collapsed",
                    help=disabled_reason,
                )
            with cols[1]:
                state_chip = ""
                if is_assigned and currently_enabled:
                    state_chip = (
                        ' <span style="background:#DCFCE7; color:#166534; '
                        'padding:1px 6px; border-radius:9999px; font-size:0.68rem; '
                        'font-weight:600;">assigned</span>'
                    )
                elif is_assigned and not currently_enabled:
                    state_chip = (
                        ' <span style="background:#E5E7EB; color:#374151; '
                        'padding:1px 6px; border-radius:9999px; font-size:0.68rem; '
                        'font-weight:600;">soft-revoked</span>'
                    )
                runtime_chip = ""
                if not is_runnable:
                    runtime_chip = (
                        f' <span style="background:#FEF3C7; color:#92400E; '
                        f'padding:1px 6px; border-radius:9999px; font-size:0.68rem; '
                        f'font-weight:600;">{runtime_status}</span>'
                    )
                st.markdown(
                    f"<span style='font-size:0.86rem; font-weight:500;'>"
                    f"{display}</span>"
                    f"<code style='font-size:0.7rem; color:#6B7280; "
                    f"margin-left:6px;'>{tool_key}</code>"
                    f"{state_chip}{runtime_chip}",
                    unsafe_allow_html=True,
                )
            with cols[2]:
                bits: list[str] = []
                if default_tier:
                    bits.append(f"`{default_tier}`")
                if iwo2_origin:
                    bits.append(f"iwo2:{iwo2_origin}")
                st.caption(" · ".join(bits) if bits else "—")

            # Apply toggle if state changed (Streamlit reruns on every
            # widget interaction; this catches the change before rerun).
            if (
                can_assign
                and is_runnable
                and new_value != currently_enabled
            ):
                try:
                    api.set_sub_agent_tool(
                        cfg["id"],
                        tool_key,
                        enabled=new_value,
                        notes=None,
                    )
                    if new_value:
                        st.toast(f"Granted {tool_key}", icon="✅")
                    else:
                        st.toast(f"Revoked {tool_key}", icon="🛑")
                    st.rerun()
                except APIError as err:
                    st.error(
                        f"Could not toggle {tool_key}: "
                        f"{err.status_code} — {err.detail}"
                    )
        st.markdown("")


# ── runtime tools (5) ─────────────────────────────────────────────────


def _render_runtime_tools_tab(
    api,  # noqa: ANN001
    cfg: dict[str, Any],
) -> None:
    """Section 5 — Runtime Tools chips.

    Mirrors IWO2 RuntimeToolsSummary: the set of tools the agent will
    actually receive at execution time, derived from the same join
    backend. Filter: runnable AND assigned AND enabled.
    """
    try:
        bundle = api.get_sub_agent_tools(cfg["id"])
    except APIError as err:
        st.error(f"Could not load runtime tools: {err.status_code} — {err.detail}")
        return

    tools = bundle.get("tools", [])
    runtime_tools = [
        t
        for t in tools
        if t.get("runtime_status") == "runnable"
        and t.get("assigned")
        and t.get("enabled")
    ]

    if not runtime_tools:
        st.warning(
            "No runtime tools currently bound to this sub-agent. The "
            "agent will execute with zero tool access until an admin "
            "assigns tools in the Tool Access tab."
        )
        return

    st.success(
        f"{len(runtime_tools)} tool(s) will be available at execution time."
    )
    chip_html = " ".join(
        f'<span style="display:inline-block; background:#DCFCE7; '
        f'color:#166534; padding:3px 10px; border-radius:9999px; '
        f'font-size:0.78rem; font-weight:600; margin:2px 4px 2px 0;">'
        f'{t.get("display_name") or t["tool_key"]}'
        f'</span>'
        for t in runtime_tools
    )
    st.markdown(chip_html, unsafe_allow_html=True)


# ── tool history (6) ──────────────────────────────────────────────────


def _render_tool_history_tab(
    api,  # noqa: ANN001
    cfg: dict[str, Any],
    *,
    can_read_audit: bool,
) -> None:
    """Section 6 — Tool History.

    Shows recent runtime tool-call audit scoped to one llm_config.
    History is runtime-only: grants/revokes stay in the global audit
    log; this tab focuses on calls, denials, failures, and cap events.
    """
    if not can_read_audit:
        st.info(
            "Tool History requires `audit_log:read`. Ask an admin to "
            "grant audit visibility for this tenant."
        )
        return

    try:
        bundle = api.get_sub_agent_tool_history(cfg["id"], limit=25)
    except APIError as err:
        st.error(
            f"Could not load tool history: {err.status_code} — {err.detail}"
        )
        return

    entries = bundle.get("entries", [])
    if not entries:
        st.caption(
            "No runtime tool events for this sub-agent yet. Once the "
            "agent executes assigned tools, recent calls and denials "
            "will appear here."
        )
        return

    tool_counts: dict[str, int] = {}
    for entry in entries:
        tool_name = entry.get("tool_name") or "cap_event"
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

    st.caption(
        f"{len(entries)} recent runtime event(s) for "
        f"`{bundle.get('agent_role', cfg['agent_role'])}`."
    )

    chip_html = " ".join(
        f'<span style="display:inline-block; background:#DBEAFE; '
        f'color:#1E40AF; padding:3px 10px; border-radius:9999px; '
        f'font-size:0.76rem; font-weight:600; margin:2px 4px 2px 0;">'
        f'{tool_name} × {count}'
        f"</span>"
        for tool_name, count in sorted(
            tool_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )
    )
    st.markdown(chip_html, unsafe_allow_html=True)

    for entry in entries[:10]:
        action = entry.get("action", "sub_agent.tool_unknown")
        tool_name = entry.get("tool_name") or "n/a"
        wo_id = entry.get("work_order_id") or "—"
        iteration = entry.get("iteration_index")
        detail = entry.get("detail") or ""
        result_size = entry.get("result_size_chars")
        bits = [f"`{action}`", f"tool `{tool_name}`", f"WO `{wo_id}`"]
        if iteration is not None:
            bits.append(f"iter `{iteration}`")
        if result_size is not None:
            bits.append(f"result chars `{result_size}`")
        st.markdown(
            f"**{entry.get('created_at', '')[:19]}** — "
            + " · ".join(bits)
        )
        if detail:
            st.caption(detail)


# ── version history (preserved from β.6) ──────────────────────────────


def _render_history_tab(  # noqa: ANN001
    api,
    cfg: dict[str, Any],
    can_admin: bool,
) -> None:
    """Preserved from Pre-Beta β.6 — version + rollback list."""
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
                disabled=not can_admin
                or (action == "initial" and v_num == 1 and len(versions) == 1),
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


# ── connection test (preserved) ───────────────────────────────────────


def _render_test_tab(  # noqa: ANN001
    api,
    cfg: dict[str, Any],
    can_admin: bool,
) -> None:
    if st.button(
        "Run connection test",
        key=f"test-{cfg['id']}",
        disabled=not can_admin,
    ):
        with st.spinner("calling provider…"):
            try:
                r = api.test_llm(agent_role=cfg["agent_role"])
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")
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


# ── disable (preserved) ───────────────────────────────────────────────


def _render_disable_tab(  # noqa: ANN001
    api,
    cfg: dict[str, Any],
    can_admin: bool,
) -> None:
    if cfg["enabled"]:
        if st.button(
            f"Disable {cfg['display_name']}",
            key=f"del-{cfg['id']}",
            disabled=not can_admin,
        ):
            try:
                api.delete_llm_config(cfg["id"])
                st.success("Disabled.")
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.detail}")
    else:
        st.caption("Already disabled. Re-enable via the Edit tab.")


# ── new sub-agent form (preserved from β.6) ───────────────────────────


def _render_new_form(api, can_admin: bool) -> None:  # noqa: ANN001
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
                "Base URL (optional)",
                placeholder="leave blank for provider default",
            )
            credential_ref = st.text_input(
                "Credential ref",
                value="credential_ref:env:GROQ_API_KEY",
            )
            enabled = st.toggle("Enabled", value=True)
        description = st.text_area("Description", height=70)
        system_prompt = st.text_area("System prompt (optional)", height=140)
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


# ── main entry point ──────────────────────────────────────────────────


def _agent_role_sort_key(cfg: dict[str, Any]) -> tuple[int, str]:
    """Order tier_1 first, tier_15 second, tier_2 alphabetical."""
    role = cfg["agent_role"]
    if role == "aiden_tier_1":
        return (0, role)
    if role == "pm_tier_15":
        return (1, role)
    return (2, role)


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">
          Sub-Agents
        </h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Tier-1 / Tier-1.5 / Tier-2 LLM configs with IWO2-parity
          surface — persona editor, LLM connection, Tool Access grid,
          Runtime Tools chips, version history. Provenance badges show
          where each sub-agent's prompt actually came from.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        configs = api.list_llm_configs()
        can_admin = api.check_permission("llm_config:write")
        can_assign = api.check_permission("sub_agent_tool:assign")
        can_read_audit = api.check_permission("audit_log:read")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    # Top-of-page combined banner so operators understand which surfaces
    # are locked before they click in.
    if not can_admin.allowed and not can_assign.allowed:
        st.info(
            f"Your role `{can_admin.role}` lacks both `llm_config:write` "
            f"and `sub_agent_tool:assign`. Edit / create / connection-test "
            f"and Tool Access toggles are disabled; read remains available."
        )
    elif not can_admin.allowed:
        _rbac_banner(
            can_admin,
            permission="llm_config:write",
            action_label="Persona / connection edit",
        )
    elif not can_assign.allowed:
        _rbac_banner(
            can_assign,
            permission="sub_agent_tool:assign",
            action_label="Tool Access toggles",
        )

    if not configs:
        st.info(
            "No LLM configs for this tenant yet — use the New Sub-Agent "
            "form below to create the first one."
        )
        return

    # Card grid — two cards per row. Streamlit's column system isn't a
    # true CSS grid but it's the closest IWO2-feeling layout we have.
    sorted_configs = sorted(configs, key=_agent_role_sort_key)
    st.markdown(
        f"<div style='color:#6B7280; font-size:0.82rem; margin:6px 0;'>"
        f"{len(sorted_configs)} sub-agent(s) for this tenant.</div>",
        unsafe_allow_html=True,
    )

    for i in range(0, len(sorted_configs), 2):
        row = sorted_configs[i : i + 2]
        cols = st.columns(len(row))
        for col, cfg in zip(cols, row):
            with col:
                with st.container(border=True):
                    _render_card_header(cfg)
                    with st.expander("Open editor", expanded=False):
                        tabs = st.tabs(
                            [
                                "Edit",
                                "Tool Access",
                                "Runtime",
                                "Tool History",
                                "Versions",
                                "Test",
                                "Disable",
                            ]
                        )
                        with tabs[0]:
                            _render_edit_form(
                                api,
                                cfg,
                                can_admin=can_admin.allowed,
                                form_key=f"edit-{cfg['id']}",
                            )
                        with tabs[1]:
                            _render_tool_access_tab(
                                api, cfg, can_assign=can_assign.allowed
                            )
                        with tabs[2]:
                            _render_runtime_tools_tab(api, cfg)
                        with tabs[3]:
                            _render_tool_history_tab(
                                api,
                                cfg,
                                can_read_audit=can_read_audit.allowed,
                            )
                        with tabs[4]:
                            _render_history_tab(
                                api, cfg, can_admin.allowed
                            )
                        with tabs[5]:
                            _render_test_tab(
                                api, cfg, can_admin.allowed
                            )
                        with tabs[6]:
                            _render_disable_tab(
                                api, cfg, can_admin.allowed
                            )

    st.divider()
    with st.expander("➕ New sub-agent", expanded=False):
        _render_new_form(api, can_admin.allowed)


main()
