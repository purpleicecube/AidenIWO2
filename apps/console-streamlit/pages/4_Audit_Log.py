"""IWO3 Console — Audit Log page.

Tenant-scoped audit rows for the current tenant. Filter by
work_order_id to scope to a single WO's lineage. Requires
`audit_log:read` — owner/admin-gated by default.
"""

from __future__ import annotations

import json
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
        page_title="IWO3 Console — Audit Log",
        page_icon="📜",
        layout="wide",
    )
    st.title("Audit Log")

    api = _api()
    if api is None:
        return

    # Preflight the gate so we can show a helpful banner instead of a
    # 403 error when the current user isn't owner/admin.
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

    wo_filter = st.text_input(
        "Filter by work_order_id (optional)", key="audit_wo_filter"
    )
    limit = st.slider(
        "Limit", min_value=10, max_value=500, value=50, step=10
    )

    try:
        rows = api.list_audit_log(
            work_order_id=wo_filter or None, limit=limit
        )
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not rows:
        st.info("No audit rows match.")
        return

    st.caption(f"{len(rows)} rows")
    for r in rows:
        with st.expander(
            f"**{r.action}** — {r.created_at[:19]} — actor `{(r.actor_user_id or '—')[:8]}…`",
            expanded=False,
        ):
            st.markdown(f"**Target:** `{r.target_type or '—'}` / `{r.target_id or '—'}`")
            st.code(json.dumps(r.metadata, indent=2, default=str), language="json")


if __name__ == "__main__":
    main()
