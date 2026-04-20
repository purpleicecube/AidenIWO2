"""System Health — FastAPI /healthz + /readyz probes + Postgres
connectivity surface."""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">System Health</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Live checks against the FastAPI runtime + Postgres backing store.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### FastAPI")
        try:
            health = api._request("GET", "/healthz")
            st.success(f"✅ `{health['status']}` · `{health['service']}` · v`{health['version']}`")
        except APIError as err:
            st.error(f"❌ {err.status_code} — {err.detail}")
    with col2:
        st.markdown("### Database")
        try:
            ready = api._request("GET", "/readyz")
            if ready.get("database") == "connected":
                st.success(f"✅ Postgres `{ready['database']}`")
            else:
                st.warning(f"⚠️ Postgres `{ready.get('database', 'unknown')}`")
        except APIError as err:
            st.error(f"❌ {err.status_code} — {err.detail}")

    st.divider()
    st.markdown("### Tenant surfaces")
    try:
        tenants = api.list_tenants()
    except APIError as err:
        st.error(f"❌ /tenants — {err.detail}")
        return
    for t in tenants:
        st.markdown(f"- `{t.designation}` · role `{t.role}` · membership `{t.membership_status}`")


main()
