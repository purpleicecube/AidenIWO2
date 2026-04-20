"""AIDEN IWO3 Operator Console — entry + navigation router.

Loop 8.3 reorganises the console to mirror the IWO2 product shell
(see WS024 reference image). Nav groups: Navigation / Environments /
Architecture / Configuration + a small Technical section for the
observability pages (audit / handoffs / output packages) that Loop
8.1/8.2 added.

Every page below `views/` reads the `ApiClient` from
`st.session_state["iwo3_api"]`, which `render_sidebar_shell()` seeds
on every rerender.
"""

from __future__ import annotations

import streamlit as st

from shell import render_sidebar_shell, render_sidebar_footer


def main() -> None:
    st.set_page_config(
        page_title="AIDEN IWO3",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render_sidebar_shell()

    pages = {
        "Navigation": [
            st.Page("views/dashboard.py", title="Dashboard", icon="🏠", default=True),
            st.Page("views/chat.py", title="Chat with Aiden", icon="💬"),
            st.Page("views/work_orders.py", title="Work Orders", icon="📋"),
            st.Page("views/submit_order.py", title="Submit Order", icon="➕"),
            st.Page("views/system_health.py", title="System Health", icon="🩺"),
        ],
        "Environments": [
            st.Page("views/workspace.py", title="Workspace", icon="🗂️"),
            st.Page("views/sandbox.py", title="Sandbox", icon="🧪"),
            st.Page("views/design_lab.py", title="Design Lab", icon="🎨"),
        ],
        "Architecture": [
            st.Page("views/tier_overview.py", title="Tier Overview", icon="📐"),
        ],
        "Configuration": [
            st.Page("views/aiden_settings.py", title="Aiden Settings", icon="⚙️"),
            st.Page("views/sub_agents.py", title="Sub-Agents", icon="🤖"),
            st.Page("views/tools.py", title="Tools", icon="🛠️"),
            st.Page("views/pipelines.py", title="Pipelines", icon="🔗"),
            st.Page("views/workflows.py", title="Workflows", icon="🔄"),
            st.Page("views/user_management.py", title="User Management", icon="👥"),
        ],
        "Technical Console": [
            st.Page("views/output_packages.py", title="Output Packages", icon="📦"),
            st.Page("views/handoffs.py", title="Handoffs", icon="🎯"),
            st.Page("views/audit_log.py", title="Audit Log", icon="📜"),
        ],
    }

    nav = st.navigation(pages, position="sidebar")

    render_sidebar_footer()

    nav.run()


if __name__ == "__main__":
    main()
else:
    main()
