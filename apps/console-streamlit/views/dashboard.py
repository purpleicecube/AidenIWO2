"""IWO3 Dashboard — IWO2 product-shell parity.

Metric cards (Total / Pending / Completed / Reopened / Awaiting
Operator / Blocked / Deferred / Archived) + Recent Work Orders panel
+ Orchestration (Tier 1 / Tier 1.5 / Tier 2) panel.

Metrics backed by the Loop 7 /work_orders list + /work_orders/metrics
(added in Loop 8.3). Where an aggregate isn't computable from the
routes we have (e.g. "Reopened" requires execution_cycles scan), the
card shows `—` with a small "route pending" hint rather than a faked
value.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def _metric_card(label: str, value: str, hint: Optional[str] = None) -> None:
    inner_hint = f'<div class="hint">{hint}</div>' if hint else ""
    st.markdown(
        f"""
        <div class="iwo3-metric">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
          {inner_hint}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _tier_card(tier: str, subtitle: str, icon: str) -> None:
    st.markdown(
        f"""
        <div class="iwo3-tier-card">
          <div class="t">{icon} {tier}</div>
          <div class="d">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _header() -> None:
    col_h, col_action = st.columns([4, 1])
    with col_h:
        st.markdown("## Dashboard")
        st.caption(
            "Monitor Aiden (Tier 1), PM (Tier 1.5), and sub-agent "
            "(Tier 2) orchestration."
        )
    with col_action:
        if st.button("＋ New Work Order", type="primary"):
            st.switch_page("views/submit_order.py")


def main() -> None:
    _header()

    api = page_requires_api()
    if api is None:
        return

    try:
        metrics = api.work_order_metrics()
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return
    except AttributeError:
        # Old ApiClient without work_order_metrics — defensive fallback.
        metrics = None

    # Metric cards (two rows, four per row on wide viewports).
    row1 = st.columns(4)
    row2 = st.columns(4)

    cards: list[tuple[str, str, Optional[str]]]
    if metrics is None:
        cards = [
            ("Total", "—", "route pending"),
            ("Pending", "—", "route pending"),
            ("Completed", "—", "route pending"),
            ("Reopened", "—", "route pending"),
            ("Awaiting Operator", "—", "route pending"),
            ("Blocked", "—", "route pending"),
            ("Deferred", "—", "route pending"),
            ("Archived", "—", "route pending"),
        ]
    else:
        c = metrics.by_status
        cards = [
            ("Total", str(metrics.total), "All work orders"),
            ("Pending", str(c.get("pending", 0)), "Awaiting Aiden review"),
            ("Completed", str(c.get("completed", 0) + c.get("done", 0)), "Successfully processed"),
            ("Reopened", str(metrics.reopened_count), "Sent back for revision"),
            ("Awaiting Operator", str(c.get("awaiting_operator", 0)), "Independent sub-agents"),
            ("Blocked", str(c.get("blocked", 0)), "Requires attention"),
            ("Deferred", str(c.get("deferred", 0)), "Decision postponed"),
            ("Archived", str(c.get("cancelled", 0)), "Removed from active view"),
        ]

    for col, (lbl, val, hint) in zip(row1 + row2, cards):
        with col:
            _metric_card(lbl, val, hint)

    st.markdown("")  # breathing room

    # Two-column lower section: Recent WOs | Orchestration
    left, right = st.columns([2, 1])

    with left:
        st.markdown('<div class="iwo3-section-head">Recent Work Orders</div>', unsafe_allow_html=True)
        try:
            wos = api.list_work_orders()
        except APIError as err:
            st.error(f"❌ {err.status_code} — {err.detail}")
            wos = []
        if not wos:
            st.caption("_No work orders in this tenant yet._")
        else:
            for wo in wos[:8]:
                c1, c2, c3 = st.columns([4, 1, 1])
                c1.markdown(
                    f"**{wo.title}**  \n"
                    f"<span style='color:#6b7aa7;font-size:0.82rem'>{wo.type} · {wo.created_at[:10]}</span>",
                    unsafe_allow_html=True,
                )
                c2.markdown(
                    f'<span class="iwo3-chip-m">{wo.priority}</span>',
                    unsafe_allow_html=True,
                )
                chip_class = "iwo3-chip-ok" if wo.status in ("completed", "done") else "iwo3-chip-m"
                c3.markdown(
                    f'<span class="{chip_class}">{wo.status}</span>',
                    unsafe_allow_html=True,
                )
            if len(wos) > 8:
                if st.button("View all →", key="dash-view-all-wos"):
                    st.switch_page("views/work_orders.py")

    with right:
        st.markdown('<div class="iwo3-section-head">Orchestration</div>', unsafe_allow_html=True)
        _tier_card("Tier 1 — Aiden", "Policy, Routing, Decisions", "🧠")
        _tier_card("Tier 1.5 — PM Coordination", "Workflow orchestration, Step coordination", "🧭")
        _tier_card("Tier 2 — Sub-Agents", "Aiden-controlled or Independent", "🤖")
        st.markdown("")
        if st.button("Workflows →", key="dash-to-workflows"):
            st.switch_page("views/workflows.py")
        if st.button("Sub-Agents →", key="dash-to-subagents"):
            st.switch_page("views/sub_agents.py")


main()
