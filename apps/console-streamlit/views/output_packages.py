"""Output Packages — tenant-scoped list + handoff chain."""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Output Packages</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Tenant-scoped output packages + linked handoffs.
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
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not packages:
        st.info("No output packages in this tenant yet.")
        return

    by_package: dict[str, list] = {}
    for h in handoffs:
        if h.output_package_id:
            by_package.setdefault(h.output_package_id, []).append(h)

    kinds = sorted({p.output_kind for p in packages})
    kind_filter = st.multiselect("Output kind", options=kinds, default=kinds)
    filtered = [p for p in packages if p.output_kind in kind_filter]
    st.caption(f"Showing {len(filtered)} / {len(packages)} packages")

    for pkg in filtered:
        with st.expander(
            f"**{pkg.title}** — `{pkg.output_kind}` · status `{pkg.status}`",
            expanded=False,
        ):
            st.markdown(f"**ID:** `{pkg.id}`")
            pkg_handoffs = by_package.get(pkg.id, [])
            if pkg_handoffs:
                st.markdown("**Handoffs:**")
                for h in pkg_handoffs:
                    cand = (
                        f" · candidate `{h.candidate_status}`"
                        if h.candidate_status != "not_candidate"
                        else ""
                    )
                    st.markdown(f"- `{h.id[:8]}…` — status `{h.status}`{cand}")
            else:
                st.caption("_No handoffs yet._")


main()
