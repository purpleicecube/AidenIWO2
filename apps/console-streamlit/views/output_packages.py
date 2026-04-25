"""Output Packages — tenant-scoped list + handoff chain.

Alpha closeout γ.3 — operator-facing output retrieval surface. Sorts
latest-first, surfaces work-order correlation, accepts a focus id from
chat (`output_packages_focus_id` in `st.session_state`) so the deep-
link button on chat lands on the relevant row already expanded.
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
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Output Packages</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Tenant-scoped output packages (latest first) with linked handoffs.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        packages = api.list_output_packages()
        handoffs = api.list_output_handoffs()
        try:
            wos = api.list_work_orders()
        except APIError:
            wos = []
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not packages:
        st.info("No output packages in this tenant yet.")
        return

    # Build lookup maps.
    by_package: dict[str, list] = {}
    for h in handoffs:
        if h.output_package_id:
            by_package.setdefault(h.output_package_id, []).append(h)

    wo_titles: dict[str, str] = {wo.id: wo.title for wo in wos}

    # Sort latest-first; rows without created_at fall to the bottom.
    def _sort_key(p):
        return (p.created_at or "", p.id)

    packages_sorted = sorted(packages, key=_sort_key, reverse=True)

    # Optional focus from chat → "Open Output Package".
    focus_id = st.session_state.pop("output_packages_focus_id", None)
    if focus_id:
        st.info(
            f"Showing the package opened from chat. Use the filter below to "
            f"see others.",
        )

    kinds = sorted({p.output_kind for p in packages})
    kind_filter = st.multiselect("Output kind", options=kinds, default=kinds)
    filtered = [p for p in packages_sorted if p.output_kind in kind_filter]
    st.caption(f"Showing {len(filtered)} / {len(packages)} packages (latest first)")

    for pkg in filtered:
        is_focused = bool(focus_id and pkg.id == focus_id)
        wo_title = (
            wo_titles.get(pkg.work_order_id) if pkg.work_order_id else None
        )
        wo_chip = f" · WO **{wo_title}**" if wo_title else ""
        with st.expander(
            f"**{pkg.title}** — `{pkg.output_kind}` · status `{pkg.status}`{wo_chip}",
            expanded=is_focused,
        ):
            cols = st.columns([2, 1])
            with cols[0]:
                st.markdown(f"**ID:** `{pkg.id}`")
                if pkg.work_order_id:
                    st.markdown(f"**Work order:** `{pkg.work_order_id}`")
                if hasattr(pkg, "correlation_id") and getattr(pkg, "correlation_id", None):
                    st.markdown(f"**Correlation:** `{pkg.correlation_id}`")
                st.markdown(f"**Created:** {_ts(pkg.created_at)}")
            with cols[1]:
                if pkg.work_order_id:
                    if st.button(
                        "Open Work Order",
                        key=f"goto-wo-{pkg.id}",
                    ):
                        st.session_state["work_orders_focus_id"] = pkg.work_order_id
                        st.switch_page("views/work_orders.py")

            pkg_handoffs = by_package.get(pkg.id, [])
            if pkg_handoffs:
                st.markdown("**Handoffs**")
                for h in pkg_handoffs:
                    cand = (
                        f" · candidate `{h.candidate_status}`"
                        if h.candidate_status != "not_candidate"
                        else ""
                    )
                    extras = []
                    if h.external_destination:
                        extras.append(f"destination `{h.external_destination}`")
                    if h.external_reference:
                        extras.append(f"ref `{h.external_reference}`")
                    extra_line = " · ".join(extras)
                    st.markdown(
                        f"- `{h.id[:8]}…` — status `{h.status}`{cand}"
                        + (f"\n  {extra_line}" if extra_line else "")
                    )
            else:
                st.caption("_No handoffs yet for this package._")


main()
