"""Audit Log — owner-gated tenant-scoped audit rows."""

from __future__ import annotations

import json

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def main() -> None:
    st.markdown(
        '<h2 style="margin:0 0 14px 0; font-size:1.5rem; font-weight:700;">Audit Log</h2>',
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        check = api.check_permission("audit_log:read")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not check.allowed:
        st.warning(
            f"Your role (`{check.role or 'none'}`) does not hold "
            f"`audit_log:read`. Switch to an owner account in the sidebar."
        )
        return

    wo_filter = st.text_input("Filter by work_order_id (optional)")
    limit = st.slider("Limit", 10, 500, 50, 10)

    try:
        rows = api.list_audit_log(work_order_id=wo_filter or None, limit=limit)
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not rows:
        st.info("No audit rows match.")
        return

    st.caption(f"{len(rows)} rows")
    for r in rows:
        with st.expander(
            f"**{r.action}** · {r.created_at[:19]} · actor `{(r.actor_user_id or '—')[:8]}…`",
            expanded=False,
        ):
            st.markdown(f"**Target:** `{r.target_type or '—'}` / `{r.target_id or '—'}`")
            st.code(json.dumps(r.metadata, indent=2, default=str), language="json")


main()
