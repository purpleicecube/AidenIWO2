"""IWO3 Operator Console — entry page.

Loop 8 Phase 8.1 — the first browser-visible IWO3 surface. Sidebar
carries a dev auth picker (tenant + user); main body shows welcome
copy + a pointer to the Work Orders page.

Visual language: aligned with IWO2 — deep navy + purple accent on
a light lavender background; Lexend for headings, Barlow for body
(configured via `.streamlit/config.toml` in the same directory).
"""

from __future__ import annotations

import os

import streamlit as st

from api_client import ApiClient, APIError


SEED_USERS: dict[str, str] = {
    "Klear Owner": "00000000-0000-4000-8000-000001000001",
    "Klear Admin": "00000000-0000-4000-8000-000001000002",
    "Klear Operator": "00000000-0000-4000-8000-000001000003",
    "Klear Reviewer": "00000000-0000-4000-8000-000001000004",
    "Klear Viewer": "00000000-0000-4000-8000-000001000005",
    "Klear Agent_System": "00000000-0000-4000-8000-000001000006",
    "FFAI Owner": "00000000-0000-4000-8000-000002000001",
    "FFAI Operator": "00000000-0000-4000-8000-000002000003",
    "Super (both tenants)": "00000000-0000-4000-8000-000099000001",
    "Intruder (no memberships)": "00000000-0000-4000-8000-000099000002",
}

DEFAULT_TENANT_CHOICES: list[tuple[str, str]] = [
    ("IWO | Klear.ai", "00000000-0000-4000-8000-00000000c001"),
    ("IWO | FreedomForge.AI", "00000000-0000-4000-8000-00000000c002"),
]


def _sidebar() -> ApiClient:
    """Renders the dev-auth picker and returns a configured ApiClient.

    The picker is a temporary Loop 8 concession — production auth is
    Loop 9+. All state lives in st.session_state so page switches keep
    the identity."""
    st.sidebar.title("IWO3 Console")
    st.sidebar.caption("Loop 8 — dev auth; production auth is Loop 9+.")

    base_url = st.sidebar.text_input(
        "API base URL",
        value=os.environ.get("IWO3_API_BASE_URL", "http://localhost:8000"),
        key="iwo3_api_base_url",
    )

    user_label = st.sidebar.selectbox(
        "Acting user (dev bearer)",
        options=list(SEED_USERS.keys()),
        index=2,  # Klear Operator — the most demo-friendly default
        key="iwo3_user_label",
    )
    tenant_label = st.sidebar.selectbox(
        "Tenant",
        options=[label for label, _ in DEFAULT_TENANT_CHOICES],
        index=0,
        key="iwo3_tenant_label",
    )
    user_id = SEED_USERS[user_label]
    client_id = next(cid for label, cid in DEFAULT_TENANT_CHOICES if label == tenant_label)

    api = ApiClient(base_url=base_url, user_id=user_id, client_id=client_id)

    # Verify the pair resolves by calling /tenants. Surfaces config
    # errors (FastAPI down, wrong headers) without dumping them in
    # every downstream page.
    try:
        tenants = api.list_tenants()
    except APIError as err:
        st.sidebar.error(f"⚠️ {err.status_code} — {err.detail}")
        tenants = []

    st.sidebar.markdown("**Tenant memberships for this user:**")
    if tenants:
        for t in tenants:
            st.sidebar.markdown(
                f"- `{t.designation}` — role **`{t.role}`**"
            )
    else:
        st.sidebar.markdown("_(no memberships — intruder or API error)_")

    st.session_state["iwo3_api"] = api
    return api


def main() -> None:
    st.set_page_config(
        page_title="IWO3 Console",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _sidebar()

    st.title("AIDEN IWO3 — Operator Console")
    st.caption("Loop 8 browser-visible MVP over the Loop 7 FastAPI runtime.")

    st.markdown(
        """
        Use the **sidebar** on the left to pick an acting user + tenant
        (dev auth only — production auth ships in Loop 9+). Then open
        one of the pages on the left to interact with IWO3:

        - **Work Orders** — list + detail + transition actions
          (retry / cancel / block / unblock / reopen).
        - **Output Packages** _(Phase 8.2)_ — package list + handoff
          chain per package.
        - **Handoffs** _(Phase 8.2)_ — candidate review
          (select / reject) for reviewers.
        - **Audit Log** _(Phase 8.2)_ — tenant-scoped audit trail.

        Role-aware UI: transition buttons disable when the current user
        lacks the permission (checked via `/permissions/check` before
        every render). Cross-tenant access is refused by RLS before it
        reaches the UI layer.
        """
    )

    st.divider()
    st.markdown(
        "*Everything you see routes through the FastAPI runtime at "
        f"`{st.session_state['iwo3_api']._base_url}` — Streamlit never "
        "touches the database directly.*"
    )


if __name__ == "__main__":
    main()
