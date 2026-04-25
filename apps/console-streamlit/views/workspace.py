"""Workspace — recent activity view (Alpha closeout γ.5).

Replaces the Loop 8.3 placeholder with a real operator-facing
dashboard of the most recent work in the tenant: latest WOs,
output packages, and handoffs. Each row deep-links via session
state to the relevant detail surface.

The IWO2 vision of a Workspace (per-operator scratch files, pinned
artefacts) is a richer concept that's deferred to MegaLoop Beta;
this v1 keeps the page useful during an Alpha walkthrough so it
doesn't look dead.
"""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def _ts(value: object) -> str:
    if not value:
        return "-"
    s = str(value)
    return s.replace("T", " ").replace("+00:00", " UTC")


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Workspace</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Recent activity for this tenant — the latest work orders, outputs,
          and handoffs. Pinned scratch files + cross-WO search are
          MegaLoop Beta scope.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        wos = api.list_work_orders()
        packages = api.list_output_packages()
        handoffs = api.list_output_handoffs()
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    # Top-line counts.
    st.markdown("### At a glance")
    cols = st.columns(4)
    cols[0].metric("Work orders", len(wos))
    cols[1].metric(
        "Open WOs",
        len([w for w in wos if w.status not in {"completed", "done", "cancelled", "failed"}]),
    )
    cols[2].metric("Output packages", len(packages))
    cols[3].metric("Handoffs", len(handoffs))

    st.divider()

    def _sort_desc(rows, key):
        return sorted(rows, key=lambda r: (getattr(r, key, "") or "", r.id), reverse=True)

    latest_wos = _sort_desc(wos, "created_at")[:8]
    latest_pkgs = _sort_desc(packages, "created_at")[:8]
    latest_handoffs = _sort_desc(handoffs, "created_at")[:8]

    col_wo, col_pkg = st.columns(2)
    with col_wo:
        st.markdown("### Latest work orders")
        if not latest_wos:
            st.caption("_None yet — try Submit Order or Chat with Aiden._")
        for wo in latest_wos:
            with st.container():
                st.markdown(
                    f"**{wo.title}** · `{wo.status}` · priority `{wo.priority}`"
                )
                st.caption(
                    f"id `{wo.id[:8]}…` · created {_ts(wo.created_at)}"
                )
                if st.button(
                    "Open", key=f"ws-wo-{wo.id}"
                ):
                    st.session_state["work_orders_focus_id"] = wo.id
                    st.switch_page("views/work_orders.py")
        if wos:
            if st.button("→ All work orders", key="ws-all-wos"):
                st.switch_page("views/work_orders.py")

    with col_pkg:
        st.markdown("### Latest output packages")
        if not latest_pkgs:
            st.caption("_None yet — outputs land here after dispatch._")
        for pkg in latest_pkgs:
            with st.container():
                st.markdown(
                    f"**{pkg.title}** · `{pkg.output_kind}` · `{pkg.status}`"
                )
                st.caption(
                    f"id `{pkg.id[:8]}…` · created {_ts(pkg.created_at)}"
                )
                if st.button(
                    "Open", key=f"ws-pkg-{pkg.id}"
                ):
                    st.session_state["output_packages_focus_id"] = pkg.id
                    st.switch_page("views/output_packages.py")
        if packages:
            if st.button("→ All output packages", key="ws-all-pkgs"):
                st.switch_page("views/output_packages.py")

    if latest_handoffs:
        st.divider()
        st.markdown("### Latest handoffs")
        for h in latest_handoffs:
            extras = []
            if h.external_destination:
                extras.append(f"destination `{h.external_destination}`")
            if h.external_reference:
                extras.append(f"ref `{h.external_reference}`")
            cand = (
                f" · candidate `{h.candidate_status}`"
                if h.candidate_status != "not_candidate"
                else ""
            )
            st.markdown(
                f"- `{h.id[:8]}…` · status `{h.status}`{cand}"
                + (f"\n  {' · '.join(extras)}" if extras else "")
            )
        if st.button("→ All handoffs", key="ws-all-handoffs"):
            st.switch_page("views/handoffs.py")


main()
