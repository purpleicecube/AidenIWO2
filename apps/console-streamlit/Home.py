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

from pathlib import Path

import streamlit as st

from shell import render_sidebar_shell, render_sidebar_footer

_FAVICON = Path(__file__).parent / "assets" / "favicon.png"


def main() -> None:
    st.set_page_config(
        page_title="AIDEN IWO3",
        page_icon=str(_FAVICON) if _FAVICON.exists() else "🧭",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={"Get help": None, "Report a bug": None, "About": None},
    )
    render_sidebar_shell()

    # Icons: Streamlit `:material/*:` (monochrome line-style; inherits
    # text color). Replaces the Loop 8.3-initial emoji set which read as
    # amateur next to IWO2's lucide-style nav.
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
        ],
        "Configuration": [
            st.Page("views/aiden_settings.py", title="Aiden Settings", icon=":material/settings:"),
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
        ],
    }

    nav = st.navigation(pages, position="sidebar")

    render_sidebar_footer()

    nav.run()


if __name__ == "__main__":
    main()
else:
    main()
