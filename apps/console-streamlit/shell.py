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
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #FFFFFF 0%, #F3F4FA 100%);
    border-right: 1px solid #E5E7F2;
  }
  [data-testid="stSidebarHeader"] + div { padding-top: 0 !important; }
  .iwo3-brand {
    display: flex; gap: 10px; align-items: center;
    padding: 14px 10px 8px 10px; border-bottom: 1px solid #E5E7F2;
    margin-bottom: 6px;
  }
  .iwo3-brand .mark {
    width: 34px; height: 34px; border-radius: 8px;
    background: linear-gradient(135deg, #8B49E2, #37517E);
    display: flex; align-items: center; justify-content: center;
    color: white; font-weight: 700;
  }
  .iwo3-brand .name { font-weight: 700; color: #091C53; line-height: 1.15; }
  .iwo3-brand .sub  { font-size: 0.78rem; color: #4a5a8a; }
  .iwo3-group-label {
    text-transform: uppercase; font-size: 0.72rem; letter-spacing: 0.06em;
    color: #4a5a8a; padding: 10px 10px 4px 10px;
  }
  .iwo3-user {
    margin-top: 12px; padding: 10px; border-top: 1px solid #E5E7F2;
    display: flex; gap: 10px; align-items: center;
  }
  .iwo3-user .avatar {
    width: 30px; height: 30px; border-radius: 50%;
    background: #091C53; color: white; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.82rem;
  }
  .iwo3-user .role { font-size: 0.72rem; color: #4a5a8a; }
  .iwo3-footer {
    padding: 6px 10px 14px 10px; font-size: 0.72rem; color: #4a5a8a;
  }
  .iwo3-metric {
    border: 1px solid #E5E7F2; border-radius: 10px; padding: 14px 16px;
    background: white;
  }
  .iwo3-metric .label { font-size: 0.78rem; color: #4a5a8a; text-transform: none; }
  .iwo3-metric .value { font-size: 2rem; font-weight: 700; color: #091C53; line-height: 1.1; }
  .iwo3-metric .hint  { font-size: 0.72rem; color: #6b7aa7; margin-top: 4px; }
  .iwo3-section-head { font-size: 1.15rem; font-weight: 700; color: #091C53; }
  .iwo3-tier-card {
    border: 1px solid #E5E7F2; border-radius: 10px; padding: 12px 14px;
    background: white; margin-bottom: 8px;
  }
  .iwo3-tier-card .t { font-weight: 700; color: #091C53; }
  .iwo3-tier-card .d { font-size: 0.82rem; color: #4a5a8a; }
  .iwo3-chip-m  { background: #E6F2FA; color: #1E5F91; padding: 2px 10px; border-radius: 999px; font-size: 0.78rem; }
  .iwo3-chip-ok { background: #E6F8EE; color: #177245; padding: 2px 10px; border-radius: 999px; font-size: 0.78rem; }
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


def render_sidebar_shell() -> ApiClient:
    """Renders the IWO2-parity sidebar: identity block → dev-auth picker
    → (the st.navigation widget will be injected by the caller) →
    user badge + version footer."""
    st.markdown(_CSS, unsafe_allow_html=True)

    # Brand identity
    st.sidebar.markdown(
        """
        <div class="iwo3-brand">
          <div class="mark">🧭</div>
          <div>
            <div class="name">AIDEN_IWO3</div>
            <div class="sub">Orchestration Engine</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Dev-auth picker (replaced by real auth in Loop 9+).
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
    st.session_state["iwo3_current_tenant_label"] = TENANT_LABELS.get(
        client_id, client_id
    )

    return api


def render_sidebar_footer() -> None:
    """User badge + version footer, rendered AFTER st.navigation has
    injected its own widgets. Mirrors IWO2's bottom-left layout."""
    # `iwo3_user_label` is a widget-owned key (the Acting-user
    # selectbox) — reading from it is fine; writing would raise
    # StreamlitAPIException. Derived state uses separate
    # `iwo3_current_*` keys populated by render_sidebar_shell().
    user_label = st.session_state.get("iwo3_user_label", "—")
    role = st.session_state.get("iwo3_current_user_role", "—")
    tenant_label = st.session_state.get("iwo3_current_tenant_label", "—")
    initials = _initials(user_label)

    st.sidebar.markdown(
        f"""
        <div class="iwo3-user">
          <div class="avatar">{initials}</div>
          <div>
            <div style="font-weight:600;color:#091C53;font-size:0.88rem;">{user_label}</div>
            <div class="role">{tenant_label} · <span class="iwo3-chip-ok">{role}</span></div>
          </div>
        </div>
        <div class="iwo3-footer">AIDEN_IWO3 · Loop 8.3 (dev)</div>
        """,
        unsafe_allow_html=True,
    )


def page_requires_api() -> Optional[ApiClient]:
    """View helper — resolves the ApiClient or renders a guiding
    message if the shell never ran (e.g., a view script invoked
    directly)."""
    api = st.session_state.get("iwo3_api")
    if api is None:
        st.info("Open **Dashboard** first — the shell sets the auth context.")
    return api
