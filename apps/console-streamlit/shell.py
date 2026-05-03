"""Loop 8.3 — IWO2-style app shell for the Streamlit console.

Single source for the sidebar identity block, dev-auth picker, user
badge, version footer, and the grouped nav registry consumed by
`st.navigation`. Every page inside `views/` pulls the configured
`ApiClient` from `st.session_state["iwo3_api"]`.

Visual guide: WS024 IWO2 reference image + docs/ui/iwo2-tokens.
Primary purple #8B49E2 accent on light lavender #F3F4FA base;
Lexend/Barlow family (falls back to sans-serif when the fonts are
not locally installed).
"""

from __future__ import annotations

import os
from typing import Optional

import streamlit as st

from api_client import ApiClient, APIError


SEED_USERS: dict[str, tuple[str, str, str]] = {
    # label -> (user_id, default_client_id, short_role)
    "Klear Owner":         ("00000000-0000-4000-8000-000001000001", "00000000-0000-4000-8000-00000000c001", "owner"),
    "Klear Admin":         ("00000000-0000-4000-8000-000001000002", "00000000-0000-4000-8000-00000000c001", "admin"),
    "Klear Operator":      ("00000000-0000-4000-8000-000001000003", "00000000-0000-4000-8000-00000000c001", "operator"),
    "Klear Reviewer":      ("00000000-0000-4000-8000-000001000004", "00000000-0000-4000-8000-00000000c001", "reviewer"),
    "Klear Viewer":        ("00000000-0000-4000-8000-000001000005", "00000000-0000-4000-8000-00000000c001", "viewer"),
    "Klear Agent_System":  ("00000000-0000-4000-8000-000001000006", "00000000-0000-4000-8000-00000000c001", "agent_system"),
    "FFAI Owner":          ("00000000-0000-4000-8000-000002000001", "00000000-0000-4000-8000-00000000c002", "owner"),
    "FFAI Operator":       ("00000000-0000-4000-8000-000002000003", "00000000-0000-4000-8000-00000000c002", "operator"),
    "Super (cross-tenant)":("00000000-0000-4000-8000-000099000001", "00000000-0000-4000-8000-00000000c001", "owner"),
    "Intruder":            ("00000000-0000-4000-8000-000099000002", "00000000-0000-4000-8000-00000000c001", "—"),
}

TENANT_LABELS: dict[str, str] = {
    "00000000-0000-4000-8000-00000000c001": "IWO | Klear.ai",
    "00000000-0000-4000-8000-00000000c002": "IWO | FreedomForge.AI",
}


# IWO2-like CSS tightening — Streamlit defaults give us too much
# whitespace between blocks and bulky sidebar icons. Keep changes
# minimal + brand-aligned.
_CSS = """
<style>
  /* ── Global tone — tighten Streamlit's default leading + restore IWO2 neutrals ── */
  html, body, [data-testid="stAppViewContainer"] {
    color: #111827;
    background: #FAFBFC;
  }
  [data-testid="stAppViewContainer"] .main .block-container {
    padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1400px;
  }
  h1, h2, h3, h4, h5 { color: #111827; letter-spacing: -0.01em; }

  /* ── Sidebar shell ── */
  [data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid #E5E7EB;
    position: relative;
  }
  /* Streamlit's default header strip carries the collapse button; we
     hide it so our .iwo3-brand can pin to top:0 (R-015 identity parity
     with IWO2). Operator console is always expanded, so no loss. */
  [data-testid="stSidebarHeader"] { display: none !important; }
  [data-testid="stSidebarContent"] { padding-top: 72px !important; }
  [data-testid="stSidebarHeader"] + div { padding-top: 0 !important; }
  [data-testid="stSidebar"] [data-testid="stSidebarNav"] {
    padding-top: 2px; padding-bottom: 2px;
  }
  [data-testid="stSidebarNav"] ul { padding: 0 4px; }
  /* Group-label tightening — uppercase with small leading */
  [data-testid="stSidebarNav"] > div > span,
  [data-testid="stSidebarNav"] [data-testid="stSidebarNavSeparator"] + span {
    font-size: 0.7rem !important; letter-spacing: 0.06em;
    color: #6B7280 !important; text-transform: uppercase;
    padding: 10px 12px 4px 12px !important;
  }
  [data-testid="stSidebarNav"] a {
    border-radius: 6px; padding: 5px 8px; font-size: 0.86rem;
    color: #374151; line-height: 1.25;
  }
  [data-testid="stSidebarNav"] a:hover { background: #F3F4F6; }
  [data-testid="stSidebarNav"] a[aria-current="page"] {
    background: #EFF6FF; color: #1E40AF; font-weight: 600;
  }
  /* Suppress the top-right hamburger + decoration strip */
  [data-testid="stToolbar"] { display: none !important; }
  [data-testid="stDecoration"] { display: none !important; }
  [data-testid="stHeader"] { background: transparent; height: 0; }

  /* Brand lives inside Streamlit's stSidebarUserContent (natural flow),
     but is absolute-positioned to the top of the sidebar so it sits
     above stSidebarNav without our having to reorder Streamlit's
     internal children. Streamlit's per-element wrapper has position:
     relative by default, which would capture our absolute positioning;
     the :has() override neutralises that wrapper for the brand's
     containing block so top:0 resolves to stSidebarContent (the whole
     sidebar area). The stSidebarContent padding-top above reserves the
     matching space so nav doesn't collide with it. */
  [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:has(.iwo3-brand) {
    position: static !important;
  }
  .iwo3-brand {
    position: absolute; top: 0; left: 0; right: 0; z-index: 10;
    background: #FFFFFF;
    display: flex; gap: 12px; align-items: center;
    padding: 18px 14px 14px 14px; border-bottom: 1px solid #E5E7EB;
    margin: 0;
  }
  .iwo3-brand .mark {
    width: 42px; height: 42px; border-radius: 10px;
    background: #2563EB;
    display: flex; align-items: center; justify-content: center;
    color: white;
    box-shadow: 0 1px 2px rgba(30, 64, 175, 0.25);
    flex-shrink: 0;
  }
  .iwo3-brand .mark svg { width: 24px; height: 24px; display: block; }
  .iwo3-brand .name {
    font-weight: 700; color: #111827; line-height: 1.15;
    letter-spacing: -0.01em; font-size: 0.98rem;
  }
  .iwo3-brand .name .tenant {
    color: #6B7280; font-weight: 500; margin: 0 2px;
  }
  .iwo3-brand .sub  { font-size: 0.76rem; color: #6B7280; margin-top: 2px; }

  .iwo3-user {
    margin-top: 12px; padding: 12px 14px; border-top: 1px solid #E5E7EB;
    display: flex; gap: 10px; align-items: center;
  }
  .iwo3-user .avatar {
    width: 34px; height: 34px; border-radius: 50%;
    background: #1E3A8A; color: white; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.82rem; letter-spacing: 0.02em;
  }
  .iwo3-user .name { font-size: 0.88rem; font-weight: 600; color: #111827; line-height: 1.2; }
  .iwo3-user .role { font-size: 0.74rem; color: #6B7280; margin-top: 1px; }
  .iwo3-chip-admin {
    background: #DBEAFE; color: #1E40AF; padding: 1px 8px;
    border-radius: 999px; font-size: 0.7rem; font-weight: 600; margin-left: 4px;
  }
  .iwo3-footer {
    padding: 4px 14px 16px 14px; font-size: 0.72rem; color: #9CA3AF;
  }

  /* ── Dashboard: metric cards ── */
  .iwo3-metric {
    border: 1px solid #E5E7EB; border-radius: 10px; padding: 14px 16px;
    background: #FFFFFF; position: relative; min-height: 100px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
  }
  .iwo3-metric .header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 2px;
  }
  .iwo3-metric .label { font-size: 0.78rem; color: #6B7280; font-weight: 500; }
  .iwo3-metric .icon {
    width: 32px; height: 32px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .iwo3-metric .icon svg { width: 18px; height: 18px; display: block; }
  .iwo3-metric .icon.blue   { background: #DBEAFE; color: #1D4ED8; }
  .iwo3-metric .icon.skyblue{ background: #E0F2FE; color: #0369A1; }
  .iwo3-metric .icon.green  { background: #D1FAE5; color: #047857; }
  .iwo3-metric .icon.amber  { background: #FEF3C7; color: #B45309; }
  .iwo3-metric .icon.red    { background: #FEE2E2; color: #B91C1C; }
  .iwo3-metric .icon.violet { background: #EDE9FE; color: #6D28D9; }
  .iwo3-metric .icon.gray   { background: #F3F4F6; color: #4B5563; }
  .iwo3-metric .value {
    font-size: 1.75rem; font-weight: 700; color: #111827;
    line-height: 1.1; letter-spacing: -0.02em; margin-top: 4px;
  }
  .iwo3-metric .hint  { font-size: 0.74rem; color: #6B7280; margin-top: 4px; }

  /* ── Dashboard: section heads ── */
  .iwo3-section-head {
    font-size: 0.98rem; font-weight: 600; color: #111827;
    margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;
  }
  .iwo3-section-head .link {
    font-size: 0.78rem; font-weight: 500; color: #2563EB;
  }

  /* ── Recent Work Orders rows ── */
  .iwo3-panel {
    border: 1px solid #E5E7EB; border-radius: 10px; background: #FFFFFF;
    padding: 16px 18px; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
  }
  .iwo3-wo-row {
    display: grid; grid-template-columns: 1fr auto auto; gap: 12px;
    align-items: center; padding: 14px 0;
    border-bottom: 1px solid #F3F4F6;
  }
  .iwo3-wo-row:last-child { border-bottom: 0; }
  .iwo3-wo-row .title { font-weight: 600; color: #111827; font-size: 0.92rem; }
  .iwo3-wo-row .meta { color: #6B7280; font-size: 0.78rem; margin-top: 3px; }
  /* Priority chip is secondary to status — slightly lighter weight. */
  .iwo3-wo-row .iwo3-chip.priority { font-weight: 500; }
  /* Section-head right-side link (replaces the chunky "View all" button). */
  .iwo3-section-head a.iwo3-link,
  .iwo3-section-head .iwo3-link {
    font-size: 0.82rem; font-weight: 500; color: #2563EB; text-decoration: none;
  }
  .iwo3-section-head a.iwo3-link:hover { text-decoration: underline; }

  /* ── Tier cards ── */
  .iwo3-tier-card {
    border: 1px solid #E5E7EB; border-left: 3px solid #2563EB;
    border-radius: 8px; padding: 12px 14px; background: #FFFFFF;
    margin-bottom: 10px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    display: flex; gap: 10px; align-items: flex-start;
  }
  .iwo3-tier-card .tier-icon {
    width: 32px; height: 32px; border-radius: 8px;
    background: #EFF6FF; color: #1E40AF;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; font-size: 0.96rem;
  }
  .iwo3-tier-card.t15 { border-left-color: #8B5CF6; }
  .iwo3-tier-card.t15 .tier-icon { background: #EDE9FE; color: #5B21B6; }
  .iwo3-tier-card.t2  { border-left-color: #F59E0B; }
  .iwo3-tier-card.t2  .tier-icon { background: #FEF3C7; color: #92400E; }
  .iwo3-tier-card .t { font-weight: 600; color: #111827; font-size: 0.92rem; }
  .iwo3-tier-card .d { font-size: 0.78rem; color: #6B7280; margin-top: 2px; }

  /* ── Status chips ── */
  .iwo3-chip {
    padding: 2px 10px; border-radius: 999px; font-size: 0.74rem; font-weight: 500;
    display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;
  }
  .iwo3-chip.blue   { background: #DBEAFE; color: #1E40AF; }
  .iwo3-chip.green  { background: #D1FAE5; color: #065F46; }
  .iwo3-chip.amber  { background: #FEF3C7; color: #92400E; }
  .iwo3-chip.red    { background: #FEE2E2; color: #991B1B; }
  .iwo3-chip.gray   { background: #F3F4F6; color: #374151; }
  .iwo3-chip.violet { background: #EDE9FE; color: #6D28D9; }
  .iwo3-chip.sky    { background: #E0F2FE; color: #0369A1; }

  /* ── Compact stat strip ── */
  .iwo3-stat-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin-top: 14px;
  }
  .iwo3-stat {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 12px 14px;
    min-width: 0;
  }
  .iwo3-stat .k {
    color: #6B7280;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.01em;
    text-transform: uppercase;
  }
  .iwo3-stat .v {
    color: #111827;
    font-size: 1rem;
    font-weight: 600;
    line-height: 1.25;
    margin-top: 4px;
    overflow-wrap: anywhere;
  }

  /* ── Streamlit button — align to IWO2 primary-blue pill ── */
  .stButton > button[kind="primary"], [data-testid="stPageLink"] button {
    background: #2563EB !important; color: white !important;
    border: none !important; border-radius: 6px !important;
    font-weight: 500 !important;
  }
  .stButton > button[kind="primary"]:hover { background: #1E40AF !important; }

  /* ── Placeholder page card ── */
  .iwo3-placeholder {
    border: 1px dashed #D1D5DB; border-radius: 10px; padding: 24px 28px;
    background: #FFFFFF; color: #4B5563;
  }
  .iwo3-placeholder h4 { color: #111827; margin: 0 0 8px 0; font-size: 1rem; font-weight: 600; }
</style>
"""


def _initials(label: str) -> str:
    parts = label.split()
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _api_from_session() -> ApiClient:
    return st.session_state["iwo3_api"]


def clear_auth_session() -> None:
    """Clear all auth/session-owned Streamlit keys and return to the
    public landing page."""
    for key in [
        "iwo3_api",
        "iwo3_logged_in",
        "iwo3_auth_mode",
        "iwo3_refresh_token",
        "iwo3_current_user_id",
        "iwo3_current_user_role",
        "iwo3_current_user_label",
        "iwo3_current_tenant_id",
        "iwo3_current_tenant_label",
    ]:
        st.session_state.pop(key, None)


def _brand_block_html(tenant_short: str) -> str:
    """IWO2-style identity block: blue square with white layers SVG +
    'AIDEN_IWO3 | <tenant>' headline + 'Orchestration Engine' subtitle."""
    layers_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
        '<polyline points="2 17 12 22 22 17"/>'
        '<polyline points="2 12 12 17 22 12"/>'
        '</svg>'
    )
    return (
        '<div class="iwo3-brand">'
        f'<div class="mark">{layers_svg}</div>'
        '<div>'
        f'<div class="name">AIDEN_IWO3<span class="tenant">|</span>'
        f'<span style="font-weight:500;color:#374151;">{tenant_short}</span></div>'
        '<div class="sub">Orchestration Engine</div>'
        '</div>'
        '</div>'
    )


def render_sidebar_shell() -> ApiClient:
    """Renders the IWO2-parity sidebar: identity block → dev-auth picker
    → (the st.navigation widget will be injected by the caller) →
    user badge + version footer."""
    st.markdown(_CSS, unsafe_allow_html=True)

    # Reserve a slot at the top of the sidebar so the identity block
    # can render ABOVE the dev-auth picker while still reading the
    # tenant the picker selected (R-015: "AIDEN_IWO3 | <tenant>" must
    # reflect the currently active tenant).
    brand_slot = st.sidebar.empty()

    if st.session_state.get("iwo3_logged_in") and "iwo3_api" in st.session_state:
        api = st.session_state["iwo3_api"]
        tenant_label = st.session_state.get(
            "iwo3_current_tenant_label", "IWO | Klear.ai"
        )
        tenant_short = tenant_label.split("|", 1)[-1].strip() or tenant_label
        brand_slot.markdown(_brand_block_html(tenant_short), unsafe_allow_html=True)

        with st.sidebar.expander("Session", expanded=False):
            auth_mode = st.session_state.get("iwo3_auth_mode", "jwt")
            if auth_mode == "dev_quick":
                st.caption("Local dev quick-login session.")
            else:
                st.caption("Signed in session.")
            if st.button("Sign out", use_container_width=True, key="iwo3_sign_out"):
                refresh_token = st.session_state.get("iwo3_refresh_token")
                try:
                    if refresh_token:
                        api.logout(refresh_token=refresh_token)
                except APIError:
                    pass
                clear_auth_session()
                st.rerun()
        return api

    # Dev-auth picker fallback for direct page work or legacy dev mode.
    with st.sidebar.expander("Dev auth", expanded=False):
        base_url = st.text_input(
            "API base URL",
            value=os.environ.get("IWO3_API_BASE_URL", "http://127.0.0.1:8000"),
            key="iwo3_api_base_url",
        )
        user_label = st.selectbox(
            "Acting user",
            options=list(SEED_USERS.keys()),
            index=2,  # Klear Operator
            key="iwo3_user_label",
        )
        default_client = SEED_USERS[user_label][1]
        tenant_choices = list(TENANT_LABELS.items())
        default_idx = next(
            (i for i, (cid, _) in enumerate(tenant_choices) if cid == default_client),
            0,
        )
        tenant_idx = st.selectbox(
            "Tenant",
            options=list(range(len(tenant_choices))),
            format_func=lambda i: tenant_choices[i][1],
            index=default_idx,
            key="iwo3_tenant_idx",
        )
        client_id = tenant_choices[tenant_idx][0]

    user_id, _dflt_client, role = SEED_USERS[user_label]
    api = ApiClient(base_url=base_url, user_id=user_id, client_id=client_id)
    # Widget-owned keys (iwo3_user_label, iwo3_tenant_idx,
    # iwo3_api_base_url) are NOT writable after the widget is
    # instantiated — Streamlit enforces that. Derived state goes into
    # separately-named keys so there's no collision.
    st.session_state["iwo3_api"] = api
    st.session_state["iwo3_current_user_id"] = user_id
    st.session_state["iwo3_current_user_role"] = role
    st.session_state["iwo3_current_tenant_id"] = client_id
    tenant_label = TENANT_LABELS.get(client_id, client_id)
    st.session_state["iwo3_current_tenant_label"] = tenant_label

    # Now fill the reserved brand slot — tenant is known.
    tenant_short = tenant_label.split("|", 1)[-1].strip() or tenant_label
    brand_slot.markdown(_brand_block_html(tenant_short), unsafe_allow_html=True)

    return api


def render_sidebar_footer() -> None:
    """User badge + version footer, rendered AFTER st.navigation has
    injected its own widgets. Mirrors IWO2's bottom-left layout."""
    user_label = st.session_state.get(
        "iwo3_current_user_label",
        st.session_state.get("iwo3_user_label", "—"),
    )
    role = st.session_state.get("iwo3_current_user_role", "—")
    tenant_label = st.session_state.get("iwo3_current_tenant_label", "—")
    initials = _initials(user_label)

    st.sidebar.markdown(
        f"""
        <div class="iwo3-user">
          <div class="avatar">{initials}</div>
          <div>
            <div class="name">{user_label}</div>
            <div class="role">{tenant_label}<span class="iwo3-chip-admin">{role}</span></div>
          </div>
        </div>
        <div class="iwo3-footer">AIDEN_IWO3 v0.8.3</div>
        """,
        unsafe_allow_html=True,
    )


def page_requires_api() -> Optional[ApiClient]:
    """View helper — resolves the ApiClient or renders a guiding
    message if the shell never ran (e.g., a view script invoked
    directly).

    Also paints a fixed top-right `← Dashboard` home affordance on every
    authenticated page so operators can return to the Dashboard from
    anywhere without hunting the sidebar."""
    api = st.session_state.get("iwo3_api")
    if api is None:
        st.info("Open **Dashboard** first — the shell sets the auth context.")
        return api
    _render_top_right_home_link()
    return api


def _render_top_right_home_link() -> None:
    """Fixed top-right `← Dashboard` link rendered on every
    authenticated page. The HTML anchor navigates via Streamlit's
    multipage routing (Dashboard is `default=True`, served at both
    `/` and `/Dashboard`). target=_self keeps the same tab so session
    state survives the navigation."""
    st.markdown(
        """
        <style>
          .iwo3-home-link {
            position: fixed;
            top: 0.85rem;
            right: 1.1rem;
            z-index: 1000;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            font-size: 0.84rem;
            font-weight: 500;
            color: #1E5F91;
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            padding: 0.4rem 0.85rem;
            text-decoration: none;
            transition: border-color 150ms ease, background 150ms ease;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
          }
          .iwo3-home-link:hover {
            background: #f8fafc;
            border-color: #1E5F91;
            color: #1E5F91;
          }
          .iwo3-home-link svg { display: block; }
        </style>
        <a class="iwo3-home-link" href="/Dashboard" target="_self">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
               viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            <path d="M9 22V12h6v10"/>
          </svg>
          Dashboard
        </a>
        """,
        unsafe_allow_html=True,
    )
