"""IWO3 Console — Work Orders page.

Lists the tenant's WOs, opens a detail pane per WO, exposes
transition buttons per the Loop 6 state-machine DAG. Every
privileged action is preflight-checked via `/permissions/check` so
role-gated buttons disable cleanly for reviewers / viewers.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from api_client import ApiClient, APIError


# Same legality table as packages/contracts/wo-wf/state_machines.ts
# (work_order rows), trimmed to the most common operator + admin
# actions so the UI doesn't overload with rarely-used transitions.
# Full DAG is still enforced server-side.
SAFE_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["processing", "cancelled", "deferred"],
    "processing": ["completed", "blocked", "awaiting_operator", "failed", "cancelled"],
    "blocked": ["processing", "cancelled", "failed"],
    "awaiting_operator": ["processing", "cancelled", "failed"],
    "deferred": ["processing", "cancelled"],
    "completed": ["processing"],  # reopen
    "done": ["processing"],
    "failed": ["processing"],
    "cancelled": [],
}


# Transition → primary permission key (belt-and-suspenders: the server
# enforces; we preflight for a smoother UI).
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


def _api() -> Optional[ApiClient]:
    api = st.session_state.get("iwo3_api")
    if api is None:
        st.warning(
            "Go back to **Home** first — the sidebar sets the auth context."
        )
    return api


def _render_transition_button(
    api: ApiClient, wo_id: str, from_status: str, to_status: str
) -> None:
    perm = PERM_FOR_TRANSITION.get(to_status, "work_order:update")
    # Preflight the permission check (cached on rerender by the
    # session's permission state; /permissions/check is read-only and
    # doesn't write audit rows).
    try:
        decision = api.check_permission(perm)
    except APIError as err:
        st.caption(f"⚠️ perm check failed for `{perm}`: {err.detail}")
        return
    label = f"→ {to_status}"
    if decision.allowed:
        if st.button(label, key=f"btn-{wo_id}-{to_status}"):
            try:
                result = api.transition_work_order(wo_id, to_status)
                st.success(
                    f"Transitioned {from_status} → {result['to']} "
                    f"(event: `{result['event']}`)"
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
    st.set_page_config(
        page_title="IWO3 Console — Work Orders", page_icon="📋", layout="wide"
    )
    st.title("Work Orders")

    api = _api()
    if api is None:
        return

    try:
        work_orders = api.list_work_orders()
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not work_orders:
        st.info("No work orders in this tenant yet.")
        return

    # Filter by status.
    statuses = sorted({wo.status for wo in work_orders})
    status_filter = st.multiselect(
        "Status filter", options=statuses, default=statuses
    )
    filtered = [wo for wo in work_orders if wo.status in status_filter]
    st.caption(f"Showing {len(filtered)} / {len(work_orders)} WOs")

    for wo in filtered:
        with st.expander(
            f"**{wo.title}** — `{wo.status}` — priority `{wo.priority}`",
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
                st.markdown("**Transitions:**")
                legal = SAFE_TRANSITIONS.get(wo.status, [])
                if not legal:
                    st.caption(f"_Terminal — no transitions out of `{wo.status}`._")
                for target in legal:
                    _render_transition_button(api, wo.id, wo.status, target)


if __name__ == "__main__":
    main()
