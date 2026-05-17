"""AIDEN IWO3 landing page + authenticated operator console router."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from api_client import APIError, ApiClient
from shell import (
    SEED_USERS,
    TENANT_LABELS,
    _brand_mark_img,
    clear_auth_session,
    render_sidebar_footer,
    render_sidebar_shell,
)

_FAVICON = Path(__file__).parent / "assets" / "favicon.png"
_DEFAULT_CLIENT_ID = "00000000-0000-4000-8000-00000000c002"
_DEFAULT_TENANT_LABEL = TENANT_LABELS.get(_DEFAULT_CLIENT_ID, "IWO | FreedomForge.AI")
_DEFAULT_DEV_USER = "Klear Owner"

_LANDING_CSS = """
<style>
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {
    display: none !important;
  }
  [data-testid="stHeader"] { background: transparent !important; }
  [data-testid="stToolbar"], [data-testid="stDecoration"] {
    display: none !important;
  }
  [data-testid="stAppViewContainer"] {
    background:
      radial-gradient(circle at 20% 20%, rgba(37, 99, 235, 0.08), transparent 24%),
      radial-gradient(circle at 78% 36%, rgba(59, 130, 246, 0.07), transparent 22%),
      linear-gradient(180deg, #FBFDFF 0%, #F7FAFC 100%);
  }
  [data-testid="stAppViewContainer"] .main .block-container {
    max-width: 1460px;
    padding-top: 0;
    padding-bottom: 0;
    padding-left: 28px;
    padding-right: 28px;
  }
  .iwo3-landing-shell {
    color: #111827;
  }
  .iwo3-topbar {
    height: 70px;
    border-bottom: 1px solid #DCE6F4;
    background: rgba(255, 255, 255, 0.86);
    backdrop-filter: blur(8px);
  }
  .iwo3-topbar-inner {
    max-width: 1460px;
    margin: 0 auto;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 34px;
  }
  .iwo3-topbar-brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .iwo3-brand-mark {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    background: #2563EB;
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 1px 2px rgba(30, 64, 175, 0.18);
  }
  .iwo3-brand-mark svg { width: 22px; height: 22px; display: block; }
  .iwo3-brand-name {
    font-size: 0.98rem;
    font-weight: 700;
    line-height: 1.15;
    letter-spacing: -0.01em;
    color: #111827;
  }
  .iwo3-brand-sub {
    margin-top: 2px;
    font-size: 0.78rem;
    color: #6B7280;
  }
  .iwo3-topbar-action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 86px;
    height: 42px;
    border-radius: 10px;
    background: #2563EB;
    color: #FFFFFF;
    font-weight: 600;
    box-shadow: 0 2px 6px rgba(37, 99, 235, 0.18);
    text-decoration: none;
  }
  .iwo3-hero-band {
    padding: 58px 0 20px 0;
  }
  .iwo3-hero-copy {
    max-width: 520px;
    padding-top: 10px;
  }
  .iwo3-hero-title {
    font-family: Georgia, "Times New Roman", serif;
    font-size: clamp(3rem, 5vw, 5rem);
    line-height: 0.96;
    letter-spacing: -0.04em;
    color: #0F172A;
    margin: 0 0 30px 0;
  }
  .iwo3-hero-title .accent { color: #1D6FD8; }
  .iwo3-hero-body {
    max-width: 520px;
    color: #5F6672;
    font-size: 1.04rem;
    line-height: 1.65;
    margin-bottom: 28px;
  }
  .iwo3-login-wrap,
  .iwo3-divider,
  .iwo3-landing-secondary {
    max-width: 420px;
  }
  .iwo3-login-wrap [data-testid="stForm"] {
    border: none !important;
    padding: 0 !important;
    background: transparent !important;
  }
  .iwo3-login-wrap [data-testid="stTextInput"] input {
    height: 2.95rem;
    border-radius: 9px;
    border: 1px solid #D1D8E3;
    background: rgba(255, 255, 255, 0.92);
    font-size: 1rem;
  }
  .iwo3-login-wrap .stButton > button,
  .iwo3-login-wrap button[kind="primary"],
  .iwo3-login-wrap [data-testid="stFormSubmitButton"] button {
    width: 100%;
    min-height: 2.95rem;
    border-radius: 9px !important;
    border: none !important;
    background: #1F73D0 !important;
    color: white !important;
    font-weight: 600 !important;
  }
  .iwo3-landing-secondary [data-testid="stButton"] > button {
    min-height: 2.8rem;
    border-radius: 9px !important;
    border: 1px solid #D9E0EA !important;
    background: rgba(255, 255, 255, 0.9) !important;
    color: #111827 !important;
    font-weight: 600 !important;
  }
  .iwo3-divider {
    display: flex;
    align-items: center;
    gap: 12px;
    color: #8B93A1;
    font-size: 0.86rem;
    margin: 12px 0 12px 0;
    max-width: 420px;
  }
  .iwo3-divider:before, .iwo3-divider:after {
    content: "";
    flex: 1;
    height: 1px;
    background: #DEE5EF;
  }
  .iwo3-mini-features {
    display: flex;
    gap: 26px;
    flex-wrap: wrap;
    margin-top: 28px;
    max-width: 420px;
    color: #65707E;
    font-size: 0.9rem;
  }
  .iwo3-mini-features .item {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .iwo3-mini-features .shield { color: #16A34A; font-weight: 700; }
  .iwo3-mini-features .spark { color: #2563EB; font-weight: 700; }
  .iwo3-demo-wrap {
    padding-top: 18px;
    padding-left: 8px;
  }
  .iwo3-demo-card {
    max-width: 620px;
    margin: 0 auto;
    padding: 34px 36px;
    border-radius: 20px;
    border: 1px solid #CFE1F8;
    background: linear-gradient(180deg, rgba(231, 241, 253, 0.92) 0%, rgba(242, 247, 253, 0.92) 100%);
    box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08);
  }
  .iwo3-demo-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid #D7E3F1;
    background: rgba(255, 255, 255, 0.8);
    font-size: 0.96rem;
    color: #1F2937;
  }
  .iwo3-demo-active {
    color: #16A34A;
    font-weight: 700;
    font-size: 0.82rem;
    letter-spacing: 0.04em;
  }
  .iwo3-demo-tree {
    margin-top: 18px;
    padding-left: 24px;
    border-left: 2px dashed #9EC4F4;
  }
  .iwo3-demo-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 14px;
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid #D7E3F1;
    background: rgba(255, 255, 255, 0.82);
    color: #1F2937;
  }
  .iwo3-demo-role {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    font-size: 0.95rem;
  }
  .iwo3-demo-badge {
    color: #6B7280;
    font-size: 0.86rem;
  }
  .iwo3-feature-band {
    padding: 18px 0 0 0;
  }
  .iwo3-feature-grid {
    margin-top: 0;
    padding: 0;
    max-width: none;
  }
  .iwo3-feature-card {
    min-height: 176px;
    padding: 26px 26px 22px 26px;
    border-radius: 18px;
    border: 1px solid #E1E8F2;
    background: rgba(255, 255, 255, 0.88);
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
  }
  .iwo3-feature-icon {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
    font-weight: 700;
    margin-bottom: 16px;
  }
  .iwo3-feature-icon.blue { background: #DBEAFE; color: #2563EB; }
  .iwo3-feature-icon.violet { background: #EDE9FE; color: #7C3AED; }
  .iwo3-feature-icon.green { background: #DCFCE7; color: #16A34A; }
  .iwo3-feature-title {
    font-size: 1.06rem;
    font-weight: 700;
    color: #1F2937;
    margin-bottom: 12px;
  }
  .iwo3-feature-copy {
    color: #6B7280;
    font-size: 0.98rem;
    line-height: 1.55;
  }
  .iwo3-landing-footer {
    max-width: 1460px;
    margin: 68px auto 0 auto;
    padding: 38px 0 42px 0;
    border-top: 1px solid #DCE6F4;
    text-align: center;
    color: #8B93A1;
  }
  .iwo3-landing-footer .name {
    color: #6B7280;
    font-size: 0.96rem;
    margin-bottom: 8px;
  }
  .iwo3-landing-footer .sub {
    font-size: 0.86rem;
    margin-bottom: 10px;
  }
  .iwo3-landing-footer .small {
    font-size: 0.78rem;
    color: #A3AAB6;
  }
  .iwo3-footer-link {
    color: inherit;
    text-decoration: none;
    border-bottom: 1px solid transparent;
  }
  .iwo3-footer-link:hover {
    color: #6B7280;
    border-bottom-color: #CBD5E1;
  }
  @media (max-width: 960px) {
    [data-testid="stAppViewContainer"] .main .block-container {
      padding-left: 20px;
      padding-right: 20px;
    }
    .iwo3-topbar-inner {
      padding: 0 20px;
    }
    .iwo3-hero-band { padding-top: 34px; }
    .iwo3-demo-wrap {
      padding-top: 10px;
      padding-left: 0;
    }
    .iwo3-feature-band { padding-top: 12px; }
  }
</style>
"""


def _set_dev_session(*, base_url: str, user_label: str) -> None:
    user_id, client_id, role = SEED_USERS[user_label]
    api = ApiClient(base_url=base_url, user_id=user_id, client_id=client_id)
    st.session_state["iwo3_api"] = api
    st.session_state["iwo3_logged_in"] = True
    st.session_state["iwo3_auth_mode"] = "dev_quick"
    st.session_state["iwo3_refresh_token"] = None
    st.session_state["iwo3_current_user_id"] = user_id
    st.session_state["iwo3_current_user_label"] = user_label
    st.session_state["iwo3_current_user_role"] = role
    st.session_state["iwo3_current_tenant_id"] = client_id
    st.session_state["iwo3_current_tenant_label"] = TENANT_LABELS.get(
        client_id, client_id
    )
    st.session_state["iwo3_api_base_url"] = base_url


def _set_jwt_session(
    *,
    base_url: str,
    email: str,
    client_id: str,
    access_token: str,
    refresh_token: str,
) -> None:
    api = ApiClient(
        base_url=base_url,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    tenant_label = _DEFAULT_TENANT_LABEL
    role = "member"
    try:
        memberships = api.list_tenants()
        membership = next(
            (item for item in memberships if item.client_id == client_id),
            None,
        )
        if membership is not None:
            tenant_label = membership.designation or tenant_label
            role = membership.role or role
    except APIError:
        pass
    st.session_state["iwo3_api"] = api
    st.session_state["iwo3_logged_in"] = True
    st.session_state["iwo3_auth_mode"] = "jwt"
    st.session_state["iwo3_refresh_token"] = refresh_token
    st.session_state["iwo3_current_user_id"] = ""
    st.session_state["iwo3_current_user_label"] = email
    st.session_state["iwo3_current_user_role"] = role
    st.session_state["iwo3_current_tenant_id"] = client_id
    st.session_state["iwo3_current_tenant_label"] = tenant_label
    st.session_state["iwo3_api_base_url"] = base_url


def _render_public_landing() -> None:
    # Initial base_url for the public landing page must come from
    # IWO3_API_BASE_URL when running in a hosted environment (Streamlit
    # Cloud, Render, etc.) — session_state is empty before first sign-in,
    # so the env var is the only signal pointing at the real API host.
    # Local-dev fallback stays at 127.0.0.1:8000.
    base_url = st.session_state.get(
        "iwo3_api_base_url",
        os.environ.get("IWO3_API_BASE_URL", "http://127.0.0.1:8000"),
    )
    st.markdown(_LANDING_CSS, unsafe_allow_html=True)
    st.markdown(
        (
            '<div class="iwo3-landing-shell">'
            '<div class="iwo3-topbar">'
            '<div class="iwo3-topbar-inner">'
            '<div class="iwo3-topbar-brand">'
            f'<div class="iwo3-brand-mark">{_brand_mark_img()}</div>'
            '<div>'
            f'<div class="iwo3-brand-name">AIDEN_IWO3 | {_DEFAULT_TENANT_LABEL.split("|", 1)[-1].strip()}</div>'
            '<div class="iwo3-brand-sub">Orchestration Engine</div>'
            '</div></div>'
            '<div class="iwo3-topbar-action">Sign In</div>'
            '</div></div>'
        ),
        unsafe_allow_html=True,
    )

    st.markdown('<div class="iwo3-hero-band">', unsafe_allow_html=True)
    hero_left, hero_right = st.columns([0.94, 1.06], gap="medium")
    with hero_left:
        st.markdown('<div class="iwo3-hero-copy">', unsafe_allow_html=True)
        st.markdown(
            (
                '<h1 class="iwo3-hero-title">Intelligent Work<br>'
                '<span class="accent">Orchestration</span></h1>'
                '<div class="iwo3-hero-body">'
                "Aiden is your AI-powered Tier 1 manager. It evaluates policy, "
                "routes work orders to specialized sub-agents, and orchestrates "
                "multi-step workflows — autonomously."
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        st.markdown('<div class="iwo3-login-wrap">', unsafe_allow_html=True)
        with st.form("iwo3-landing-login", border=False):
            tenant_choices = list(TENANT_LABELS.items())
            tenant_default_idx = next(
                (i for i, (cid, _) in enumerate(tenant_choices) if cid == _DEFAULT_CLIENT_ID),
                0,
            )
            tenant_idx = st.selectbox(
                "Tenant",
                options=list(range(len(tenant_choices))),
                format_func=lambda i: tenant_choices[i][1],
                index=tenant_default_idx,
                key="iwo3_login_tenant_idx",
                help="Pick the tenant you belong to before entering your credentials.",
            )
            chosen_client_id = tenant_choices[tenant_idx][0]
            email = st.text_input(
                "Email",
                key="iwo3_login_email",
                placeholder="Email",
                label_visibility="collapsed",
            )
            password = st.text_input(
                "Password",
                key="iwo3_login_password",
                placeholder="Password",
                type="password",
                label_visibility="collapsed",
            )
            sign_in = st.form_submit_button("Sign In", use_container_width=True, type="primary")
        st.markdown("</div>", unsafe_allow_html=True)
        if sign_in:
            try:
                api = ApiClient(base_url=base_url)
                tokens = api.login(
                    email=email.strip(),
                    password=password,
                    client_id=chosen_client_id,
                )
                _set_jwt_session(
                    base_url=base_url,
                    email=email.strip(),
                    client_id=chosen_client_id,
                    access_token=tokens["access_token"],
                    refresh_token=tokens["refresh_token"],
                )
                st.rerun()
            except APIError as err:
                detail = err.detail
                if isinstance(detail, dict) and detail.get("error") == "invalid_credentials":
                    st.error("Sign in failed. Check your email and password.")
                elif err.status_code == 0:
                    st.error("Could not reach the IWO3 API. Start FastAPI on http://127.0.0.1:8000.")
                else:
                    st.error(f"Sign in failed: {detail}")
        st.markdown('<div class="iwo3-divider">or</div>', unsafe_allow_html=True)
        st.markdown('<div class="iwo3-landing-secondary">', unsafe_allow_html=True)
        if st.button("Quick Login (Local Dev)    ->", key="iwo3_quick_login", use_container_width=True):
            _set_dev_session(base_url=base_url, user_label=_DEFAULT_DEV_USER)
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown(
            (
                '<div class="iwo3-mini-features">'
                '<div class="item"><span class="shield">◔</span><span>Role-based access</span></div>'
                '<div class="item"><span class="spark">⌘</span><span>Multi-LLM support</span></div>'
                '</div>'
            ),
            unsafe_allow_html=True,
        )
        with st.expander("Developer options", expanded=False):
            new_base_url = st.text_input(
                "API base URL",
                value=base_url,
                key="iwo3_landing_base_url",
            )
            if new_base_url != base_url:
                st.session_state["iwo3_api_base_url"] = new_base_url
        st.markdown("</div>", unsafe_allow_html=True)

    with hero_right:
        st.markdown('<div class="iwo3-demo-wrap">', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="iwo3-demo-card">
              <div class="iwo3-demo-head">
                <div><span style="color:#22C55E;font-size:1.2rem;">●</span> Aiden (Tier 1) — Policy Gate</div>
                <div class="iwo3-demo-active">ACTIVE</div>
              </div>
              <div class="iwo3-demo-tree">
                <div class="iwo3-demo-row">
                  <div class="iwo3-demo-role"><span style="color:#2563EB;">⌘</span> General Executor</div>
                  <div class="iwo3-demo-badge">groq/llama-3.3</div>
                </div>
                <div class="iwo3-demo-row">
                  <div class="iwo3-demo-role"><span style="color:#8B5CF6;">⌘</span> Incident Handler</div>
                  <div class="iwo3-demo-badge">groq/llama-3.3</div>
                </div>
                <div class="iwo3-demo-row">
                  <div class="iwo3-demo-role"><span style="color:#F97316;">⌘</span> Deploy Executor</div>
                  <div class="iwo3-demo-badge">groq/llama-3.3</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="iwo3-feature-band">', unsafe_allow_html=True)
    card_cols = st.columns(3, gap="large")
    cards = [
        ("blue", "⌁", "LLM-Powered Routing", "Aiden evaluates every work order against policy rules using AI, then routes to the right sub-agent automatically."),
        ("violet", "⇅", "Multi-Step Workflows", "Build reusable workflow templates with step dependencies, conditions, retry policies, and operator assignments."),
        ("green", "◔", "Human-in-the-Loop", "Blocked decisions surface for human review. Reopen, edit, and reprocess completed work with full audit trails."),
    ]
    for col, (tone, icon, title, body) in zip(card_cols, cards):
        with col:
            st.markdown(
                (
                    f'<div class="iwo3-feature-card"><div class="iwo3-feature-icon {tone}">{icon}</div>'
                    f'<div class="iwo3-feature-title">{title}</div>'
                    f'<div class="iwo3-feature-copy">{body}</div></div>'
                ),
                unsafe_allow_html=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class="iwo3-landing-footer">
          <div class="name">AIDEN_IWO3 — Intelligent Work Orchestration</div>
          <div class="sub">Lead Developer & Principal Technical Architect: Darrel Vaughn | LuaAzullaB</div>
          <div class="small"><a class="iwo3-footer-link" href="/attributions" target="_self">Attributions &amp; Licenses</a></div>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_authenticated_console() -> None:
    render_sidebar_shell()
    pages = {
        "Navigation": [
            st.Page("views/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True),
            st.Page("views/chat.py", title="Chat with Aiden", icon=":material/forum:"),
            st.Page("views/work_orders.py", title="Work Orders", icon=":material/assignment:"),
            st.Page("views/submit_order.py", title="Submit Order", icon=":material/add_circle_outline:"),
            st.Page("views/system_health.py", title="System Health", icon=":material/monitor_heart:"),
        ],
        "Environments": [
            st.Page("views/workspace.py", title="Workspace", icon=":material/folder_open:"),
            st.Page("views/sandbox.py", title="Sandbox", icon=":material/science:"),
            st.Page("views/design_lab.py", title="Design Lab", icon=":material/palette:"),
        ],
        "Architecture": [
            st.Page("views/tier_overview.py", title="Tier Overview", icon=":material/layers:"),
            st.Page("views/attributions.py", title="Attributions", icon=":material/account_balance:", url_path="attributions"),
        ],
        "Configuration": [
            st.Page("views/aiden_settings.py", title="Aiden Settings", icon=":material/settings:"),
            st.Page("views/canonical_facts.py", title="Canonical Facts", icon=":material/verified:"),
            st.Page("views/sub_agents.py", title="Sub-Agents", icon=":material/smart_toy:"),
            st.Page("views/tools.py", title="Tools", icon=":material/build:"),
            st.Page("views/pipelines.py", title="Pipelines", icon=":material/conversion_path:"),
            st.Page("views/workflows.py", title="Workflows", icon=":material/account_tree:"),
            st.Page("views/user_management.py", title="User Management", icon=":material/group:"),
        ],
        "Technical Console": [
            st.Page("views/output_packages.py", title="Output Packages", icon=":material/inventory_2:"),
            st.Page("views/handoffs.py", title="Handoffs", icon=":material/send:"),
            st.Page("views/audit_log.py", title="Audit Log", icon=":material/history:"),
            st.Page("views/ops_memory_health.py", title="Memory Health", icon=":material/health_and_safety:"),
        ],
    }
    nav = st.navigation(pages, position="sidebar")
    render_sidebar_footer()
    nav.run()


def _render_public_router() -> None:
    pages = [
        st.Page(_render_public_landing, title="Home", url_path="", default=True),
        st.Page(
            "views/attributions.py",
            title="Attributions",
            url_path="attributions",
        ),
    ]
    nav = st.navigation(pages, position="hidden")
    nav.run()


def main() -> None:
    st.set_page_config(
        page_title="AIDEN IWO3",
        page_icon=str(_FAVICON) if _FAVICON.exists() else "🧭",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={"Get help": None, "Report a bug": None, "About": None},
    )
    if st.session_state.get("iwo3_logged_in"):
        _render_authenticated_console()
    else:
        clear_auth_session()
        _render_public_router()


if __name__ == "__main__":
    main()
else:
    main()
