"""MegaLoop Theta — Tools Locker page.

IWO2-parity operator surface for `/tool_catalog`. Replaces the Loop 8.3
placeholder with a card-list overview + Deploy Tool 7-tab edit modal +
Import Skills filesystem scan modal + Test Connection flow for MCP
servers.

The page is read-write for `tool_catalog:create / update / delete /
import_skill / test_mcp` — granted to owner + admin. Other roles see
the read-only card list (RBAC blocks the action buttons server-side
anyway).

Each tab maps to the backend's column groups so saves round-trip
cleanly:
  Identity   — tool_type radio + name/slug/description/category/status/version
  Skill      — skill_content + skill_instructions + trigger_conditions
  Code       — source_code + entry_point + runtime_environment + sandbox_config
  MCP        — mcp_config (transport / command / args / env) + test connection
  Creds      — credentials list (key/value/isSecret/description)
  I/O        — input_schema + output_schema (raw JSON Schema)
  Govern     — access_tier + concurrency + lease + daily_usage_limit + cost +
               requires_approval
  Access     — usage_instructions (operator-authored agent guide)
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


_TOOL_TYPES: list[tuple[str, str, str]] = [
    ("skill",         "Claude Skill",      "Prompt-injected skill loaded into agent context (SKILL.md format)"),
    ("python_code",   "Python Code",       "Sandboxed Python script executed in isolated environment"),
    ("slash_command", "Slash Command",     "Agent-invokable slash command with structured input/output"),
    ("cli",           "CLI Tool",          "Command-line tool executed via shell"),
    ("api",           "API Endpoint",      "External API endpoint with authentication"),
    ("webhook",       "Webhook",           "Inbound/outbound webhook integration"),
    ("mcp_server",    "MCP Server",        "Model Context Protocol server providing tools/resources"),
]
_CATEGORIES = [
    "search", "document", "rendering", "design", "data", "ops",
    "introspection", "skill_only",
]
_RUNTIME_STATUSES = ["runnable", "catalog_only", "planned", "legacy"]
_DEFAULT_TIERS = ["tier_1", "tier_2", "either"]
_ACCESS_TIERS = ["any", "tier_1", "tier_2"]


def _show_skill_tab(tool_type: str) -> bool:
    return tool_type in ("skill", "mcp_server")


def _show_code_tab(tool_type: str) -> bool:
    return tool_type in ("python_code", "cli", "slash_command")


def _show_mcp_tab(tool_type: str) -> bool:
    return tool_type == "mcp_server"


_EDIT_KEY = "iwo3_tools_locker_edit"
_VIEW_KEY = "iwo3_tools_locker_view"
_IMPORT_OPEN_KEY = "iwo3_tools_locker_import"
_MCP_TEST_RESULT = "iwo3_tools_locker_mcp_test"


def _empty_tool() -> dict[str, Any]:
    return {
        "tool_key": "", "display_name": "", "description": "",
        "category": "data", "runtime_status": "planned",
        "default_tier": "tier_2", "tool_type": "skill",
        "iwo2_origin": None, "handler_ref": None, "args_schema": {},
        "enabled": True, "notes": None,
        "version_label": "1.0.0", "execution_mode": "prompt_injection",
        "skill_content": None, "skill_instructions": None,
        "trigger_conditions": [],
        "source_code": None, "entry_point": None,
        "runtime_environment": None, "sandbox_config": {},
        "mcp_config": {},
        "credentials": [],
        "usage_instructions": None,
        "input_schema": {}, "output_schema": {},
        "access_tier": "any", "max_concurrent": 0,
        "default_lease_seconds": 300, "max_lease_seconds": 3600,
        "daily_usage_limit": None, "cost_ceiling_per_day": None,
        "requires_approval": False, "restricted": False,
        "restricted_reason": None,
    }


def _label_for_type(value: str) -> str:
    for v, label, _ in _TOOL_TYPES:
        if v == value:
            return label
    return value


# IWO2-parity pastel badge palette: subtle bg + matching darker text,
# narrow padding, no shadow. Replaces the v0.1.0 saturated-color
# treatment that operators flagged as visually heavy.
_BADGE_PALETTE: dict[str, tuple[str, str]] = {
    "active":      ("#dcfce7", "#166534"),  # emerald
    "inactive":    ("#f3f4f6", "#6b7280"),  # grey
    "restricted":  ("#fee2e2", "#991b1b"),  # red
    # Tool type
    "skill":         ("#eff6ff", "#1d4ed8"),  # subtle blue
    "python_code":   ("#eff6ff", "#1d4ed8"),
    "slash_command": ("#ecfeff", "#155e75"),
    "cli":           ("#ecfeff", "#155e75"),
    "api":           ("#eff6ff", "#1d4ed8"),
    "webhook":       ("#ecfeff", "#155e75"),
    "mcp_server":    ("#e0e7ff", "#3730a3"),  # subtle indigo
    # Adornments
    "skill_md":  ("#ede9fe", "#6d28d9"),  # violet for SKILL.md badge
    "creds":     ("#fef3c7", "#92400e"),  # amber for credentials chip
    "category":  ("#f3f4f6", "#374151"),  # neutral grey
    "version":   ("transparent", "#6b7280"),  # borderless tiny grey
}


def _badge(text: str, palette_key: str, *, icon: Optional[str] = None) -> str:
    """IWO2-style pastel badge — pastel background + colored text + no
    border. Optional `icon` is a Streamlit material-icon name rendered
    as inline HTML to stay within the markdown surface (Streamlit
    parses :material/x: only inside button labels and st.markdown text,
    not inside arbitrary inline HTML, so we emit the unicode glyph
    fallback when an icon is requested)."""
    bg, fg = _BADGE_PALETTE.get(palette_key, ("#f3f4f6", "#374151"))
    icon_html = (
        f'<span style="font-size:0.7rem; margin-right:3px;">{icon}</span>'
        if icon
        else ""
    )
    border = "none" if bg == "transparent" else "none"
    return (
        f'<span style="background:{bg}; color:{fg}; padding:1px 7px; '
        f'border-radius:4px; font-size:0.68rem; font-weight:500; '
        f'margin-right:5px; border:{border}; vertical-align:middle; '
        f'display:inline-block;">{icon_html}{text}</span>'
    )


def _status_badge(enabled: bool, restricted: bool) -> str:
    if restricted:
        return _badge("restricted", "restricted")
    if enabled:
        return _badge("active", "active")
    return _badge("inactive", "inactive")


def _type_badge(tool_type: Optional[str]) -> str:
    if not tool_type:
        return ""
    return _badge(_label_for_type(tool_type), tool_type)


# Map tool_type to a Streamlit material icon used as the leading
# glyph in the tool's display name. Streamlit renders :material/x:
# tokens via Material Symbols Outlined when they appear in markdown
# text or button labels (NOT inside arbitrary inline HTML), so we
# emit them directly into the st.markdown content alongside the
# bolded name.
_TYPE_ICON: dict[str, str] = {
    "skill":         ":material/bolt:",
    "python_code":   ":material/code:",
    "slash_command": ":material/terminal:",
    "cli":           ":material/terminal:",
    "api":           ":material/public:",
    "webhook":       ":material/link:",
    "mcp_server":    ":material/dns:",
}


def _type_icon_token(tool_type: Optional[str]) -> str:
    return _TYPE_ICON.get(tool_type or "", ":material/build:")


def _toggle_view(tool_key: Optional[str]) -> None:
    st.session_state[_VIEW_KEY] = tool_key


def _toggle_edit(tool_key: Optional[str]) -> None:
    st.session_state[_EDIT_KEY] = tool_key


def _render_card(api, tool: dict[str, Any], can_write: bool) -> None:
    """IWO2-parity card layout:
        [type-icon glyph] **Display Name**  [active]
        `tool_key` (mono caption)
        Description (2-line clamp via CSS)
        [Type] [category] [SKILL.md if any] [Creds if any]   v1.0.0
                                                                    [👁] [✏] [🗑]
    Action buttons use Streamlit material-icon syntax for monochrome
    parity with IWO2's lucide-React look. Status badge follows the
    title; type/category land on a discrete bottom row so the eye
    parses the hierarchy exactly the way IWO2 does.
    """
    with st.container(border=True):
        col1, col2 = st.columns([6, 1])
        with col1:
            # Title row: leading material icon + bold name + status pill
            status_html = _status_badge(
                tool.get("enabled", True), tool.get("restricted", False)
            )
            icon_token = _type_icon_token(tool.get("tool_type"))
            st.markdown(
                f"{icon_token} &nbsp;**{tool.get('display_name', tool['tool_key'])}**"
                f" &nbsp; {status_html}",
                unsafe_allow_html=True,
            )
            # Slug + description block
            slug = tool["tool_key"]
            desc = (tool.get("description") or "").strip()
            st.markdown(
                f'<div style="margin-top:-4px; margin-bottom:6px;">'
                f'<code style="font-size:0.72rem; color:#6b7280; '
                f'background:transparent; padding:0;">{slug}</code>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if desc:
                st.markdown(
                    f'<div style="font-size:0.82rem; color:#4b5563; '
                    f'line-height:1.4; margin-bottom:6px; '
                    f'display:-webkit-box; -webkit-line-clamp:2; '
                    f'-webkit-box-orient:vertical; overflow:hidden;">{desc}</div>',
                    unsafe_allow_html=True,
                )
            # Bottom badge row — type / category / SKILL.md / Creds / version
            bottom = (
                _type_badge(tool.get("tool_type"))
                + _badge(tool.get("category", ""), "category")
            )
            if tool.get("skill_content"):
                bottom += _badge("SKILL.md", "skill_md")
            if tool.get("credentials"):
                bottom += _badge("Creds", "creds")
            bottom += _badge(
                f"v{tool.get('version_label', '1.0.0')}", "version"
            )
            st.markdown(bottom, unsafe_allow_html=True)
        with col2:
            view_btn, edit_btn, del_btn = st.columns(3, gap="small")
            with view_btn:
                if st.button(
                    ":material/visibility:",
                    key=f"view-{tool['tool_key']}",
                    help="View",
                    use_container_width=True,
                ):
                    _toggle_view(tool["tool_key"])
                    st.rerun()
            with edit_btn:
                if st.button(
                    ":material/edit:",
                    key=f"edit-{tool['tool_key']}",
                    help="Edit",
                    disabled=not can_write,
                    use_container_width=True,
                ):
                    _toggle_edit(tool["tool_key"])
                    st.rerun()
            with del_btn:
                if st.button(
                    ":material/delete:",
                    key=f"del-{tool['tool_key']}",
                    help="Delete",
                    disabled=not can_write,
                    use_container_width=True,
                ):
                    try:
                        api.delete_tool(tool["tool_key"])
                        st.toast(f"Deleted {tool['tool_key']}")
                        st.rerun()
                    except APIError as err:
                        st.error(f"Delete failed: {err.status_code} — {err.detail}")


def _render_view_modal(api, tool_key: str) -> None:
    try:
        all_rows = api.list_tool_catalog(enabled=True) + api.list_tool_catalog(enabled=False)
        all_tools = {t["tool_key"]: t for t in all_rows}
    except APIError as err:
        st.error(f"Failed to load tool: {err.status_code} — {err.detail}")
        return
    tool = all_tools.get(tool_key)
    if tool is None:
        st.error(f"Tool not found: {tool_key}")
        return

    @st.dialog(f"View: {tool.get('display_name', tool_key)}", width="large")
    def _dialog() -> None:
        st.markdown(
            _status_badge(tool.get("enabled", True), tool.get("restricted", False))
            + _type_badge(tool.get("tool_type"))
            + _badge(tool.get("category", ""), "category")
            + _badge(f"v{tool.get('version_label', '1.0.0')}", "version"),
            unsafe_allow_html=True,
        )
        st.caption(f"`{tool['tool_key']}`")
        st.write(tool.get("description") or "_no description_")
        c1, c2 = st.columns(2)
        with c1:
            if tool.get("runtime_status"):
                st.metric("Runtime status", tool["runtime_status"])
        with c2:
            if tool.get("execution_mode"):
                st.metric("Execution mode", tool["execution_mode"])
        if tool.get("skill_content"):
            with st.expander("SKILL.md body", expanded=False):
                st.code(tool["skill_content"], language="markdown")
        if tool.get("source_code"):
            with st.expander("Source code", expanded=False):
                st.code(
                    tool["source_code"],
                    language=tool.get("runtime_environment") or "text",
                )
        if tool.get("mcp_config"):
            with st.expander("MCP config", expanded=False):
                st.json(tool["mcp_config"])
        if tool.get("credentials"):
            with st.expander(f"Credentials ({len(tool['credentials'])})", expanded=False):
                for c in tool["credentials"]:
                    name = c.get("key", "?")
                    value = "••••••" if c.get("isSecret") else c.get("value", "")
                    st.markdown(f"- `{name}` — {value}")
        if tool.get("usage_instructions"):
            with st.expander("Usage instructions", expanded=False):
                st.markdown(tool["usage_instructions"])
        cols = st.columns(2)
        with cols[0]:
            if st.button("Close"):
                _toggle_view(None)
                st.rerun()
        with cols[1]:
            if st.button("Edit", type="primary"):
                _toggle_view(None)
                _toggle_edit(tool_key)
                st.rerun()

    _dialog()


def _render_identity_tab(state: dict[str, Any]) -> None:
    type_idx = next(
        (i for i, (v, _, _) in enumerate(_TOOL_TYPES) if v == state.get("tool_type")),
        0,
    )
    selected = st.radio(
        "Tool type",
        options=[v for v, _, _ in _TOOL_TYPES],
        index=type_idx,
        format_func=_label_for_type,
        captions=[d for _, _, d in _TOOL_TYPES],
        key="locker-tool-type",
    )
    state["tool_type"] = selected
    c1, c2 = st.columns(2)
    with c1:
        state["display_name"] = st.text_input(
            "Display name",
            value=state.get("display_name", ""),
            placeholder="e.g. Klear PPTX Skill",
            key="locker-display-name",
        )
    with c2:
        state["tool_key"] = st.text_input(
            "Slug (tool_key)",
            value=state.get("tool_key", ""),
            placeholder="e.g. klear_pptx_skill",
            key="locker-tool-key",
            help="Lowercase letters, digits, underscore, hyphen.",
        )
    state["description"] = st.text_area(
        "Description",
        value=state.get("description", ""),
        height=80,
        help="Agents use this to decide when to load the tool.",
        key="locker-description",
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        cur = state.get("category", "data")
        idx = _CATEGORIES.index(cur) if cur in _CATEGORIES else 0
        state["category"] = st.selectbox("Category", _CATEGORIES, index=idx, key="locker-category")
    with c2:
        cur = state.get("runtime_status", "planned")
        idx = _RUNTIME_STATUSES.index(cur) if cur in _RUNTIME_STATUSES else 0
        state["runtime_status"] = st.selectbox("Runtime status", _RUNTIME_STATUSES, index=idx, key="locker-runtime-status")
    with c3:
        cur = state.get("default_tier", "tier_2")
        idx = _DEFAULT_TIERS.index(cur) if cur in _DEFAULT_TIERS else 1
        state["default_tier"] = st.selectbox("Default tier", _DEFAULT_TIERS, index=idx, key="locker-default-tier")
    c1, c2, c3 = st.columns(3)
    with c1:
        state["version_label"] = st.text_input("Version", value=state.get("version_label", "1.0.0"), key="locker-version")
    with c2:
        state["enabled"] = st.toggle("Enabled", value=bool(state.get("enabled", True)), key="locker-enabled")
    with c3:
        state["restricted"] = st.toggle("Restricted", value=bool(state.get("restricted", False)), key="locker-restricted")


def _render_skill_tab(state: dict[str, Any]) -> None:
    st.info(
        "Claude SKILL.md format. This is the Level 2 content loaded into "
        "the agent's context when triggered."
    )
    state["skill_content"] = st.text_area(
        "Skill content (SKILL.md body)",
        value=state.get("skill_content") or "",
        height=300,
        placeholder="# My Skill\n\n## Quick Start\n...\n\n## Instructions\n1. ...\n2. ...",
        key="locker-skill-content",
    )
    state["skill_instructions"] = st.text_area(
        "Additional instructions (optional)",
        value=state.get("skill_instructions") or "",
        height=100,
        placeholder="Extra constraints, guardrails, or safety notes for the agent.",
        key="locker-skill-instructions",
    )
    st.markdown("**Trigger conditions** — auto-load patterns")
    triggers = state.get("trigger_conditions") or []
    if not isinstance(triggers, list):
        triggers = []
    for i, trig in enumerate(triggers):
        c1, c2, c3 = st.columns([3, 3, 1])
        with c1:
            trig["pattern"] = st.text_input(
                f"Pattern {i + 1}",
                value=trig.get("pattern", ""),
                placeholder="e.g. when user mentions PDFs",
                key=f"locker-trig-pat-{i}",
                label_visibility="collapsed",
            )
        with c2:
            trig["description"] = st.text_input(
                f"Desc {i + 1}",
                value=trig.get("description", ""),
                placeholder="Description",
                key=f"locker-trig-desc-{i}",
                label_visibility="collapsed",
            )
        with c3:
            if st.button("✕", key=f"locker-trig-rm-{i}"):
                triggers.pop(i)
                state["trigger_conditions"] = triggers
                st.rerun()
    if st.button("➕ Add trigger", key="locker-trig-add"):
        triggers.append({"pattern": "", "description": ""})
        state["trigger_conditions"] = triggers
        st.rerun()
    state["trigger_conditions"] = triggers


def _render_code_tab(state: dict[str, Any]) -> None:
    st.info(
        "Source code for python_code / cli / slash_command tools. "
        "Persistence-only in MegaLoop Theta v1 — runtime sandbox executor "
        "ships in a follow-up loop."
    )
    state["entry_point"] = st.text_input(
        "Entry point",
        value=state.get("entry_point") or "",
        placeholder="e.g. main.py:run",
        key="locker-entry-point",
    )
    state["runtime_environment"] = st.text_input(
        "Runtime environment",
        value=state.get("runtime_environment") or "",
        placeholder="e.g. python3.11",
        key="locker-runtime-env",
    )
    state["source_code"] = st.text_area(
        "Source code",
        value=state.get("source_code") or "",
        height=320,
        placeholder="def run(input):\n    ...",
        key="locker-source-code",
    )
    sandbox_str = st.text_area(
        "Sandbox config (JSON)",
        value=json.dumps(state.get("sandbox_config") or {}, indent=2),
        height=120,
        key="locker-sandbox-config",
    )
    try:
        state["sandbox_config"] = json.loads(sandbox_str) if sandbox_str.strip() else {}
    except json.JSONDecodeError as exc:
        st.warning(f"sandbox_config is not valid JSON: {exc}")


def _render_mcp_tab(api, state: dict[str, Any]) -> None:
    st.info(
        "MCP server configuration. Sub-agents connect to this server to "
        "access the tools it exposes. Access tier auto-pins to Tier 2."
    )
    cfg: dict[str, Any] = dict(state.get("mcp_config") or {})
    c1, c2 = st.columns(2)
    with c1:
        cfg["serverName"] = st.text_input(
            "Server name",
            value=cfg.get("serverName") or cfg.get("server_name") or "",
            placeholder="my-mcp-server",
            key="locker-mcp-server-name",
        )
    with c2:
        transport = st.selectbox(
            "Transport",
            ["stdio", "sse"],
            index=0 if cfg.get("transport", "stdio") == "stdio" else 1,
            key="locker-mcp-transport",
        )
        cfg["transport"] = transport
    if transport == "stdio":
        cfg["command"] = st.text_input(
            "Command", value=cfg.get("command", ""), placeholder="npx",
            key="locker-mcp-command",
        )
        args_raw = cfg.get("args", [])
        args_str = ", ".join(str(a) for a in args_raw) if isinstance(args_raw, list) else str(args_raw)
        new_args = st.text_input(
            "Arguments (comma-separated)",
            value=args_str,
            placeholder="-y, @modelcontextprotocol/server-filesystem, /tmp",
            key="locker-mcp-args",
        )
        cfg["args"] = [a.strip() for a in new_args.split(",") if a.strip()]
    else:
        cfg["url"] = st.text_input(
            "Server URL", value=cfg.get("url", ""),
            placeholder="https://mcp.example.com/sse",
            key="locker-mcp-url",
        )

    env = cfg.get("env") or {}
    env_pairs = list(env.items()) if isinstance(env, dict) else []
    st.markdown("**Environment variables**")
    new_env: dict[str, str] = {}
    for i, (k, v) in enumerate(env_pairs):
        c1, c2, c3 = st.columns([3, 4, 1])
        with c1:
            k_new = st.text_input(
                f"Key {i + 1}", value=k, key=f"locker-mcp-env-k-{i}",
                label_visibility="collapsed", placeholder="KEY",
            )
        with c2:
            v_new = st.text_input(
                f"Val {i + 1}", value=str(v), key=f"locker-mcp-env-v-{i}",
                label_visibility="collapsed", placeholder="value or env:VAR_NAME",
            )
        with c3:
            removed = st.button("✕", key=f"locker-mcp-env-rm-{i}")
        if not removed and k_new:
            new_env[k_new] = v_new
    if st.button("➕ Add env var", key="locker-mcp-env-add"):
        new_env["NEW_VAR"] = ""
    cfg["env"] = new_env
    state["mcp_config"] = cfg
    state["access_tier"] = "tier_2"

    if st.button(
        "🔌 Test connection",
        key="locker-mcp-test",
        disabled=transport == "sse",
    ):
        try:
            with st.spinner("Opening MCP session…"):
                result = api.test_mcp_connection(cfg)
            st.session_state[_MCP_TEST_RESULT] = result
        except APIError as err:
            st.session_state[_MCP_TEST_RESULT] = {
                "ok": False,
                "error": f"{err.status_code} — {err.detail}",
            }

    last = st.session_state.get(_MCP_TEST_RESULT)
    if last:
        if last.get("ok"):
            st.success(
                f"✓ Connected — {last.get('tool_count', 0)} tools "
                f"({last.get('latency_ms', 0)}ms)"
            )
            names = last.get("tool_names") or []
            if names:
                st.code(", ".join(names))
        else:
            st.error(
                f"✕ {last.get('kind', 'failed')} — "
                f"{last.get('error', 'unknown error')}"
            )


def _render_creds_tab(state: dict[str, Any]) -> None:
    st.info(
        "API keys, secrets, env vars. For secrets, use `env:VARIABLE_NAME` "
        "to reference system env instead of storing values directly."
    )
    creds = state.get("credentials") or []
    if not isinstance(creds, list):
        creds = []
    new_creds: list[dict[str, Any]] = []
    for i, c in enumerate(creds):
        col_k, col_v, col_desc, col_sec, col_rm = st.columns([3, 4, 3, 1, 1])
        with col_k:
            k = st.text_input(
                f"Key {i + 1}", value=c.get("key", ""), key=f"locker-cred-k-{i}",
                label_visibility="collapsed", placeholder="API_KEY",
            )
        with col_v:
            placeholder = "env:OPENAI_API_KEY" if c.get("isSecret") else "https://api.example.com"
            v = st.text_input(
                f"Val {i + 1}", value=c.get("value", ""),
                key=f"locker-cred-v-{i}",
                type="password" if c.get("isSecret") else "default",
                label_visibility="collapsed", placeholder=placeholder,
            )
        with col_desc:
            d = st.text_input(
                f"Desc {i + 1}", value=c.get("description", ""),
                key=f"locker-cred-d-{i}",
                label_visibility="collapsed", placeholder="What is this for?",
            )
        with col_sec:
            sec = st.toggle(
                "Sec", value=bool(c.get("isSecret", True)),
                key=f"locker-cred-sec-{i}",
                label_visibility="collapsed",
            )
        with col_rm:
            rm = st.button("✕", key=f"locker-cred-rm-{i}")
        if not rm and (k or v or d):
            new_creds.append(
                {"key": k, "value": v, "description": d, "isSecret": sec}
            )
    if st.button("➕ Add credential", key="locker-cred-add"):
        new_creds.append(
            {"key": "", "value": "", "description": "", "isSecret": True}
        )
    state["credentials"] = new_creds


def _render_io_tab(state: dict[str, Any]) -> None:
    st.info(
        "JSON Schema for what this tool expects as input and what it returns. "
        "Helps agents understand how to call the tool and parse results."
    )
    in_str = st.text_area(
        "Input schema (JSON)",
        value=json.dumps(state.get("input_schema") or {}, indent=2),
        height=180,
        key="locker-input-schema",
    )
    try:
        state["input_schema"] = json.loads(in_str) if in_str.strip() else {}
    except json.JSONDecodeError as exc:
        st.warning(f"input_schema is not valid JSON: {exc}")
    out_str = st.text_area(
        "Output schema (JSON)",
        value=json.dumps(state.get("output_schema") or {}, indent=2),
        height=180,
        key="locker-output-schema",
    )
    try:
        state["output_schema"] = json.loads(out_str) if out_str.strip() else {}
    except json.JSONDecodeError as exc:
        st.warning(f"output_schema is not valid JSON: {exc}")


def _render_govern_tab(state: dict[str, Any]) -> None:
    st.info(
        "Lease + concurrency + restricted gates. Persistence-only in v1; "
        "runtime checkout enforcement ships in a follow-up loop."
    )
    cur = state.get("access_tier", "any")
    idx = _ACCESS_TIERS.index(cur) if cur in _ACCESS_TIERS else 0
    state["access_tier"] = st.selectbox(
        "Access tier", _ACCESS_TIERS, index=idx, key="locker-access-tier"
    )
    c1, c2 = st.columns(2)
    with c1:
        state["max_concurrent"] = st.number_input(
            "Max concurrent (0 = unlimited)",
            min_value=0,
            value=int(state.get("max_concurrent") or 0),
            key="locker-max-concurrent",
        )
    with c2:
        dlim = state.get("daily_usage_limit")
        new_dlim = st.number_input(
            "Daily usage limit (0 = unlimited)",
            min_value=0,
            value=int(dlim) if dlim is not None else 0,
            key="locker-daily-limit",
        )
        state["daily_usage_limit"] = new_dlim if new_dlim > 0 else None
    c1, c2 = st.columns(2)
    with c1:
        state["default_lease_seconds"] = st.number_input(
            "Default lease (sec)",
            min_value=10,
            value=int(state.get("default_lease_seconds") or 300),
            key="locker-default-lease",
        )
    with c2:
        state["max_lease_seconds"] = st.number_input(
            "Max lease (sec)",
            min_value=30,
            value=int(state.get("max_lease_seconds") or 3600),
            key="locker-max-lease",
        )
    state["cost_ceiling_per_day"] = st.text_input(
        "Cost ceiling per day (optional)",
        value=state.get("cost_ceiling_per_day") or "",
        placeholder="e.g. $50.00",
        key="locker-cost-ceiling",
    ) or None
    state["requires_approval"] = st.toggle(
        "Requires operator approval before each checkout",
        value=bool(state.get("requires_approval", False)),
        key="locker-requires-approval",
    )
    if state.get("restricted"):
        state["restricted_reason"] = st.text_area(
            "Restricted reason",
            value=state.get("restricted_reason") or "",
            height=80,
            key="locker-restricted-reason",
        )


def _render_access_tab(state: dict[str, Any]) -> None:
    st.info(
        "Tell the agent how to invoke this tool, what to expect, working examples. "
        "This is what the agent reads after checkout."
    )
    state["usage_instructions"] = st.text_area(
        "Usage instructions",
        value=state.get("usage_instructions") or "",
        height=320,
        placeholder=(
            "## How to Use This Tool\n\n"
            "### Invocation\nCall via: `/my-tool --query \"...\" --limit 10`\n\n"
            "### Authentication\nThe API key is at env:MY_API_KEY...\n\n"
            "### Example Request\n```\n...\n```\n\n"
            "### Expected Response\n```json\n{...}\n```"
        ),
        key="locker-usage-instructions",
    )


def _render_edit_modal(api, tool_key: Optional[str]) -> None:
    is_new = tool_key is None
    state_key = f"iwo3_locker_state_{tool_key or '__new__'}"
    if state_key not in st.session_state:
        if is_new:
            st.session_state[state_key] = _empty_tool()
        else:
            try:
                tools = api.list_tool_catalog(enabled=True) + api.list_tool_catalog(enabled=False)
                found = next((t for t in tools if t["tool_key"] == tool_key), None)
                if found is None:
                    st.error(f"Tool not found: {tool_key}")
                    return
                st.session_state[state_key] = dict(found)
            except APIError as err:
                st.error(f"Load failed: {err.status_code} — {err.detail}")
                return

    state = st.session_state[state_key]

    @st.dialog(
        "Deploy Tool" if is_new else f"Edit: {state.get('display_name', tool_key)}",
        width="large",
    )
    def _dialog() -> None:
        tabs_visible: list[tuple[str, str, Callable[..., None]]] = [
            ("Identity", "🆔", _render_identity_tab),
        ]
        tt = state.get("tool_type", "skill")
        if _show_skill_tab(tt):
            tabs_visible.append(("Skill", "📜", _render_skill_tab))
        if _show_code_tab(tt):
            tabs_visible.append(("Code", "</>", _render_code_tab))
        if _show_mcp_tab(tt):
            tabs_visible.append(("MCP", "🔌", lambda s: _render_mcp_tab(api, s)))
        tabs_visible.extend(
            [
                ("Creds", "🔑", _render_creds_tab),
                ("I/O", "🔁", _render_io_tab),
                ("Govern", "🛡", _render_govern_tab),
                ("Access", "📖", _render_access_tab),
            ]
        )
        tab_widgets = st.tabs([f"{icon} {name}" for name, icon, _ in tabs_visible])
        for (name, _icon, render_fn), tab in zip(tabs_visible, tab_widgets):
            with tab:
                render_fn(state)

        st.divider()
        cols = st.columns([2, 1, 1])
        with cols[0]:
            st.caption(
                f"{len(tabs_visible)}/7 — Fill out applicable tabs before deploying"
            )
        with cols[1]:
            if st.button("Cancel", use_container_width=True):
                _toggle_edit(None)
                st.session_state.pop(state_key, None)
                st.rerun()
        with cols[2]:
            if st.button(
                "Deploy" if is_new else "Update",
                type="primary",
                use_container_width=True,
            ):
                if not state.get("tool_key") or not state.get("display_name"):
                    st.error("tool_key and display_name are required.")
                    return
                try:
                    if is_new:
                        body = {
                            k: v
                            for k, v in state.items()
                            if k not in ("created_at", "updated_at")
                        }
                        api.create_tool(body)
                        st.toast("Tool deployed", icon="✅")
                    else:
                        body = {
                            k: v
                            for k, v in state.items()
                            if k
                            not in (
                                "tool_key",
                                "created_at",
                                "updated_at",
                                "iwo2_origin",
                                "handler_ref",
                            )
                        }
                        api.update_tool(state["tool_key"], body)
                        st.toast("Tool updated", icon="💾")
                    _toggle_edit(None)
                    st.session_state.pop(state_key, None)
                    st.session_state.pop(_MCP_TEST_RESULT, None)
                    st.rerun()
                except APIError as err:
                    st.error(f"Save failed: {err.status_code} — {err.detail}")

    _dialog()


def _render_import_modal(api) -> None:
    @st.dialog("Import Skills", width="large")
    def _dialog() -> None:
        try:
            data = api.list_available_skills()
        except APIError as err:
            st.error(f"Scan failed: {err.status_code} — {err.detail}")
            return
        st.caption(f"Skills directory: `{data['skills_dir']}`")
        skills = data.get("skills", [])
        if not skills:
            st.info("No SKILL.md directories found.")
            return
        for s in skills:
            with st.container(border=True):
                col1, col2 = st.columns([6, 1])
                with col1:
                    badges = (
                        _badge(s["category"], "category")
                        + (
                            _badge("imported", "active")
                            if s["already_imported"]
                            else ""
                        )
                        + _badge(f"{s['file_count']} files", "version")
                    )
                    st.markdown(
                        f":material/bolt: &nbsp;**{s['name']}**  &nbsp; {badges}",
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"`{s['dir_name']}` — {(s.get('description') or '')[:200]}"
                    )
                with col2:
                    if st.button(
                        "Import",
                        key=f"locker-import-{s['dir_name']}",
                        disabled=s["already_imported"],
                    ):
                        try:
                            api.import_skill(dir_name=s["dir_name"])
                            st.toast(f"Imported {s['dir_name']}", icon="📥")
                            st.rerun()
                        except APIError as err:
                            st.error(
                                f"Import failed: {err.status_code} — {err.detail}"
                            )
        if st.button("Close", key="locker-import-close"):
            st.session_state[_IMPORT_OPEN_KEY] = False
            st.rerun()

    _dialog()


def main() -> None:
    api = page_requires_api()
    if api is None:
        return

    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">
          Tools Locker
        </h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Deploy and govern agentic tools — Claude Skills, code blocks, slash
          commands, MCP servers, and API integrations.
        </div>
        """,
        unsafe_allow_html=True,
    )

    can_write = False
    try:
        decision = api.check_permission("tool_catalog:create")
        can_write = decision.allowed
    except APIError:
        pass

    bar = st.columns([1, 1, 4])
    with bar[0]:
        if st.button(
            ":material/file_download: Import Skills",
            use_container_width=True,
            disabled=not can_write,
        ):
            st.session_state[_IMPORT_OPEN_KEY] = True
            st.rerun()
    with bar[1]:
        if st.button(
            ":material/add: Deploy Tool",
            type="primary",
            use_container_width=True,
            disabled=not can_write,
        ):
            _toggle_edit("__new__")
            st.rerun()
    with bar[2]:
        if not can_write:
            st.caption(
                "_Read-only — `tool_catalog:create` not granted. Owner/admin "
                "role required to deploy or import._"
            )

    show_disabled = st.toggle(
        "Show inactive tools", value=False, key="locker-show-disabled"
    )
    try:
        tools = api.list_tool_catalog(enabled=True)
        if show_disabled:
            tools = tools + api.list_tool_catalog(enabled=False)
    except APIError as err:
        st.error(f"Failed to load catalog: {err.status_code} — {err.detail}")
        return

    if not tools:
        st.info("No tools yet — Deploy Tool or Import Skills to get started.")
        return

    st.caption(f"{len(tools)} tools registered")
    for tool in tools:
        _render_card(api, tool, can_write)

    edit_target = st.session_state.get(_EDIT_KEY)
    if edit_target is not None:
        _render_edit_modal(
            api, None if edit_target == "__new__" else edit_target
        )
    view_target = st.session_state.get(_VIEW_KEY)
    if view_target is not None:
        _render_view_modal(api, view_target)
    if st.session_state.get(_IMPORT_OPEN_KEY):
        _render_import_modal(api)


main()
