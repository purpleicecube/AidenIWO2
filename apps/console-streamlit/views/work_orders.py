"""Work Orders — IWO3 Console.

List + detail + transitions. Each transition button preflights the
required permission via /permissions/check so role-denied actions
render disabled with a "requires X" tooltip; the server-side
requirePermission is still the authoritative gate.
"""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api


SAFE_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["processing", "cancelled", "deferred"],
    "processing": ["completed", "blocked", "awaiting_operator", "failed", "cancelled"],
    "blocked": ["processing", "cancelled", "failed"],
    "awaiting_operator": ["processing", "cancelled", "failed"],
    "deferred": ["processing", "cancelled"],
    "completed": ["processing"],
    "done": ["processing"],
    "failed": ["processing"],
    "cancelled": [],
}


PERM_FOR_TRANSITION: dict[str, str] = {
    "processing": "work_order:submit",
    "completed": "work_order:update",
    "done": "work_order:update",
    "blocked": "work_order:update",
    "awaiting_operator": "work_order:update",
    "failed": "work_order:update",
    "cancelled": "work_order:cancel",
    "deferred": "work_order:update",
}


def _transition_button(api, wo_id: str, from_status: str, to_status: str) -> None:
    perm = PERM_FOR_TRANSITION.get(to_status, "work_order:update")
    try:
        decision = api.check_permission(perm)
    except APIError as err:
        st.caption(f"⚠️ perm check failed: {err.detail}")
        return
    label = f"→ {to_status}"
    if decision.allowed:
        if st.button(label, key=f"btn-{wo_id}-{to_status}"):
            try:
                result = api.transition_work_order(wo_id, to_status)
                st.success(
                    f"Transitioned {from_status} → {result['to']} (event: `{result['event']}`)"
                )
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")
    else:
        st.button(
            label,
            key=f"btn-{wo_id}-{to_status}",
            disabled=True,
            help=f"Denied — requires `{perm}` (your role: `{decision.role}`)",
        )


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Work Orders</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Tenant-scoped work orders with role-aware transition actions.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        wos = api.list_work_orders()
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not wos:
        st.info("No work orders in this tenant yet.")
        if st.button("＋ Create one"):
            st.switch_page("views/submit_order.py")
        return

    statuses = sorted({wo.status for wo in wos})
    status_filter = st.multiselect("Status", options=statuses, default=statuses)
    filtered = [wo for wo in wos if wo.status in status_filter]
    st.caption(f"Showing {len(filtered)} / {len(wos)} work orders")

    for wo in filtered:
        with st.expander(
            f"**{wo.title}** — `{wo.status}` · priority `{wo.priority}`",
            expanded=False,
        ):
            col_meta, col_actions = st.columns([2, 1])
            with col_meta:
                st.markdown(f"**ID:** `{wo.id}`")
                st.markdown(f"**Type:** `{wo.type}`")
                if wo.description:
                    st.markdown(f"**Description:** {wo.description}")
                if wo.correlation_id:
                    st.markdown(f"**Correlation:** `{wo.correlation_id}`")
                st.markdown(f"**Created:** {wo.created_at}")
                st.markdown(f"**Updated:** {wo.updated_at}")
            with col_actions:
                st.markdown("**Transitions**")
                legal = SAFE_TRANSITIONS.get(wo.status, [])
                if not legal:
                    st.caption(f"_Terminal — no transitions out of `{wo.status}`._")
                for target in legal:
                    _transition_button(api, wo.id, wo.status, target)


main()
