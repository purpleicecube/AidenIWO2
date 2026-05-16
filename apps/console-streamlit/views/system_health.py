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

    st.divider()
    st.markdown("### Sub-Agent Runtime Status")
    st.caption(
        "Live wiring + degraded-surface matrix per "
        "IWO3_SUBAGENT_WIRING_MATRIX_AND_STATUS_SURFACE_v0.1.0. "
        "Computed from runtime truth — not hand-maintained."
    )
    try:
        status = api._request("GET", "/system/sub-agent-wiring-status")
    except APIError as err:
        st.error(f"❌ /system/sub-agent-wiring-status — {err.detail}")
        return

    summary = status.get("summary", {})
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric(
            "Tier-1 (Aiden)",
            "live" if summary.get("tier_1_live") else "off",
        )
    with s2:
        st.metric(
            "Tier-1.5 (PM)",
            "live" if summary.get("pm_live") else "off",
        )
    with s3:
        st.metric(
            "Tier-2 in branded chains",
            int(summary.get("tier_2_branded_chain_roles", 0)),
        )
    with s4:
        degraded = int(summary.get("degraded_roles", 0))
        st.metric(
            "Degraded roles",
            degraded,
            delta=("attention" if degraded > 0 else None),
            delta_color="inverse" if degraded > 0 else "normal",
        )

    roles = status.get("roles", [])
    if not roles:
        st.info("No role rows returned.")
    else:
        # Render as a structured table. Streamlit's st.dataframe
        # gives a sortable + scrollable view that fits the matrix.
        rows = []
        for r in roles:
            rows.append(
                {
                    "Role": r.get("display_name") or r.get("role_key"),
                    "Layer": r.get("layer"),
                    "LLM enabled": "✓" if r.get("llm_enabled") else "—",
                    "Direct path": "✓" if r.get("direct_work_order_path") else "—",
                    "Workflow path": "✓" if r.get("workflow_path") else "—",
                    "Branded chain": "✓" if r.get("branded_chain_path") else "—",
                    "Surfaces": ", ".join(r.get("surfaces") or []) or "—",
                    "Degraded": "⚠️" if r.get("degraded") else "—",
                    "Last invoked": r.get("last_invoked_at") or "—",
                    "Last success": r.get("last_success_at") or "—",
                    "Last failure": r.get("last_failure_at") or "—",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

        # Per-role degraded reasons (collapsed). Surfaces only when at
        # least one role is degraded so the page stays clean otherwise.
        degraded_rows = [r for r in roles if r.get("degraded")]
        if degraded_rows:
            with st.expander(f"Degraded reasons ({len(degraded_rows)})"):
                for r in degraded_rows:
                    st.markdown(
                        f"**{r.get('display_name') or r.get('role_key')}** — "
                        f"{r.get('degraded_reason') or 'no reason recorded'}"
                    )

    st.caption(
        f"Generated at `{status.get('generated_at', '?')}` · "
        f"baseline `{status.get('baseline_commit', '?')}`"
    )


main()
