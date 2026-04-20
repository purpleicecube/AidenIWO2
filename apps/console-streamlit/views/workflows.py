"""Workflows — list + status chips + transition buttons (admin-gated)."""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def main() -> None:
    st.markdown("## 🔄 Workflows")
    st.caption("Tenant workflows — pause, resume, archive.")

    api = page_requires_api()
    if api is None:
        return

    try:
        workflows = api.list_workflows()
        can_update = api.check_permission("workflow:update")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not workflows:
        st.info("No workflows in this tenant yet.")
        return

    for wf in workflows:
        with st.expander(f"**{wf.display_name}** — `{wf.status}`", expanded=False):
            st.markdown(f"**Key:** `{wf.key}`")
            st.markdown(f"**ID:** `{wf.id}`")
            if wf.description:
                st.markdown(f"**Description:** {wf.description}")
            cols = st.columns(4)
            targets = {
                "active": ["paused", "archived"],
                "paused": ["active", "archived"],
                "archived": [],
            }.get(wf.status, [])
            for i, target in enumerate(targets):
                with cols[i]:
                    if can_update.allowed:
                        if st.button(
                            f"→ {target}",
                            key=f"wf-{wf.id}-{target}",
                        ):
                            try:
                                api.transition_workflow(wf.id, target)
                                st.success(f"Workflow → {target}")
                                st.rerun()
                            except APIError as err:
                                st.error(f"❌ {err.detail}")
                    else:
                        st.button(
                            f"→ {target}",
                            key=f"wf-{wf.id}-{target}",
                            disabled=True,
                            help=f"Needs workflow:update (your role: {can_update.role})",
                        )


main()
