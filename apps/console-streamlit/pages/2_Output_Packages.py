"""IWO3 Console — Output Packages page.

Tenant-scoped list + detail. Detail view shows the handoffs chained
to the package; candidate review actions live on the Handoffs page.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from api_client import ApiClient, APIError


def _api() -> Optional[ApiClient]:
    api = st.session_state.get("iwo3_api")
    if api is None:
        st.warning("Go back to **Home** first — the sidebar sets auth context.")
    return api


def main() -> None:
    st.set_page_config(
        page_title="IWO3 Console — Output Packages",
        page_icon="📦",
        layout="wide",
    )
    st.title("Output Packages")

    api = _api()
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

    # Index handoffs by package id for detail rendering.
    handoffs_by_package: dict[str, list] = {}
    for h in handoffs:
        if h.output_package_id:
            handoffs_by_package.setdefault(h.output_package_id, []).append(h)

    kinds = sorted({p.output_kind for p in packages})
    kind_filter = st.multiselect(
        "Output kind filter", options=kinds, default=kinds
    )
    filtered = [p for p in packages if p.output_kind in kind_filter]
    st.caption(f"Showing {len(filtered)} / {len(packages)} packages")

    for pkg in filtered:
        with st.expander(
            f"**{pkg.title}** — `{pkg.output_kind}` — status `{pkg.status}`",
            expanded=False,
        ):
            st.markdown(f"**ID:** `{pkg.id}`")
            st.markdown(f"**Client:** `{pkg.client_id}`")
            pkg_handoffs = handoffs_by_package.get(pkg.id, [])
            if pkg_handoffs:
                st.markdown("**Handoffs:**")
                for h in pkg_handoffs:
                    cand = f" — candidate `{h.candidate_status}`" if h.candidate_status != "not_candidate" else ""
                    st.markdown(
                        f"- `{h.id[:8]}…` — status `{h.status}`{cand}"
                    )
            else:
                st.caption("_No handoffs yet._")


if __name__ == "__main__":
    main()
