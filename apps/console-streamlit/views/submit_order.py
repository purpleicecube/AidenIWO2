"""Submit Order — create a new Work Order.

First-pass form backed by the Loop 8.3 `POST /work_orders` route.
Fields map to the Drizzle `work_orders` schema + the DigiFLOW intake
contract (Loop 3 Phase 3.3).
"""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api

WO_TYPES = [
    "content_brief",
    "research_brief",
    "ad_hoc",
]
WO_PRIORITIES = ["low", "medium", "high", "critical"]


def main() -> None:
    st.markdown("## ＋ Submit Order")
    st.caption("Create a new Work Order for the active tenant.")

    api = page_requires_api()
    if api is None:
        return

    # Preflight the gate so we can surface a friendly message rather
    # than waiting for a 403 after form submission.
    try:
        decision = api.check_permission("work_order:create")
    except APIError as err:
        st.error(f"❌ perm check failed: {err.detail}")
        return

    if not decision.allowed:
        st.warning(
            f"Your role (`{decision.role or 'none'}`) does not hold "
            f"`work_order:create`. Switch to an operator/admin/owner in "
            f"the sidebar dev-auth picker."
        )
        return

    with st.form("submit-order", clear_on_submit=False):
        title = st.text_input("Title *", placeholder="Draft RMIS one-pager for April brief")
        description = st.text_area(
            "Description",
            placeholder="What should this work order produce? Who is the audience?",
        )
        col1, col2 = st.columns(2)
        with col1:
            wo_type = st.selectbox("Type", options=WO_TYPES, index=0)
        with col2:
            priority = st.selectbox("Priority", options=WO_PRIORITIES, index=1)
        correlation_id = st.text_input(
            "Correlation ID",
            placeholder="e.g. wo-klear-rmis-apr-001",
            help="Optional — groups related work for audit lineage.",
        )

        submitted = st.form_submit_button("Submit Order", type="primary")
        if submitted:
            if not title.strip():
                st.error("Title is required.")
                return
            try:
                resp = api.create_work_order(
                    title=title.strip(),
                    description=description.strip() or None,
                    wo_type=wo_type,
                    priority=priority,
                    correlation_id=correlation_id.strip() or None,
                )
            except APIError as err:
                if err.status_code == 404 and "not_implemented" in str(err.detail):
                    st.warning(
                        "**Route pending** — the FastAPI `POST /work_orders` "
                        "endpoint is not yet available on this server. The "
                        "form shape is correct; it will work once the route "
                        "lands. Reported by server: "
                        f"{err.detail}"
                    )
                else:
                    st.error(f"❌ {err.status_code} — {err.detail}")
                return

            st.success(
                f"✅ Work Order created: `{resp.get('id', '—')}` "
                f"(status: `{resp.get('status', '—')}`)"
            )
            st.caption(
                "Open **Work Orders** to see it in the list and trigger "
                "transitions."
            )


main()
