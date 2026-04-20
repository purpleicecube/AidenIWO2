"""IWO3 Dashboard — IWO2 product-shell parity (Loop 8.3 visual rev).

Metric cards (Total / Pending / Completed / Reopened / Awaiting
Operator / Blocked / Deferred / Archived) + Recent Work Orders panel
+ Orchestration (Tier 1 / Tier 1.5 / Tier 2) panel.

Visual tokens + HTML structure follow the IWO2 reference image and
the Design Critic subagent spec (Loop 8.3 visual-quality revision).
Metrics backed by `/work_orders/metrics`; Recent WOs by the scoped
`/work_orders` list. Row + card HTML is rendered in one `st.markdown`
block per visual group so CSS grid/flex layout survives Streamlit's
per-element wrappers.
"""

from __future__ import annotations

from html import escape
from typing import Optional

import streamlit as st

from api_client import APIError, WorkOrderRow
from shell import page_requires_api


# Icon glyph per metric (Streamlit `:material/*:` can't render inside
# raw HTML; we use very small text letters as stand-in inside the
# colored icon chip — they echo the IWO2 reference's compact labels).
METRIC_ICONS: dict[str, tuple[str, str]] = {
    # label → (tint, short glyph)
    "Total": ("blue", "T"),
    "Pending": ("amber", "P"),
    "Completed": ("green", "✓"),
    "Reopened": ("violet", "⟲"),
    "Awaiting Operator": ("blue", "A"),
    "Blocked": ("red", "!"),
    "Deferred": ("gray", "D"),
    "Archived": ("gray", "A"),
}


def _metric_card(label: str, value: str, hint: Optional[str] = None) -> None:
    tint, glyph = METRIC_ICONS.get(label, ("gray", "•"))
    hint_html = f'<div class="hint">{escape(hint)}</div>' if hint else ""
    # Flat HTML (no leading whitespace) — see _recent_wo_panel docstring
    # for the indented-code-block parsing caveat.
    html = (
        '<div class="iwo3-metric">'
        f'<div class="header"><div class="label">{escape(label)}</div>'
        f'<div class="icon {tint}">{glyph}</div></div>'
        f'<div class="value">{escape(value)}</div>'
        f'{hint_html}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _tier_card(
    tier_title: str, subtitle: str, glyph: str, variant: str = ""
) -> None:
    cls = f"iwo3-tier-card {variant}".strip()
    html = (
        f'<div class="{cls}">'
        f'<div class="tier-icon">{escape(glyph)}</div>'
        '<div>'
        f'<div class="t">{escape(tier_title)}</div>'
        f'<div class="d">{escape(subtitle)}</div>'
        '</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _status_chip_class(status: str) -> str:
    if status in ("completed", "done"):
        return "iwo3-chip green"
    if status == "failed":
        return "iwo3-chip red"
    if status in ("blocked", "awaiting_operator"):
        return "iwo3-chip amber"
    return "iwo3-chip blue"


def _priority_chip_class(priority: str) -> str:
    if priority == "critical":
        return "iwo3-chip red"
    if priority == "high":
        return "iwo3-chip amber"
    return "iwo3-chip blue"


def _header() -> None:
    col_h, col_action = st.columns([4, 1])
    with col_h:
        st.markdown(
            """
            <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Dashboard</h2>
            <div style="color:#6B7280; font-size:0.86rem;">
              Monitor Aiden (Tier 1), PM (Tier 1.5), and sub-agent (Tier 2) orchestration.
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_action:
        if st.button("+ New Work Order", type="primary", key="dash-new-wo"):
            st.switch_page("views/submit_order.py")


def _recent_wo_panel(wos: list[WorkOrderRow]) -> None:
    """Render every WO row inside ONE markdown block so the flex-grid
    layout survives (Streamlit wraps each st.markdown in a div which
    breaks cross-element CSS grid).

    Flatten HTML to a single line so Streamlit's markdown parser does
    NOT treat 4-space-indented lines as an indented code block. That
    was bug #1 in the first visual rev — the panel rendered as literal
    HTML source inside a `<pre>`.
    """
    rows_html: list[str] = []
    for wo in wos[:8]:
        row = (
            f'<div class="iwo3-wo-row">'
            f'<div><div class="title">{escape(wo.title)}</div>'
            f'<div class="meta">{escape(wo.type)} · {escape(wo.created_at[:10])}</div></div>'
            f'<span class="{_priority_chip_class(wo.priority)}">{escape(wo.priority)}</span>'
            f'<span class="{_status_chip_class(wo.status)}">{escape(wo.status)}</span>'
            f'</div>'
        )
        rows_html.append(row)
    more_link = ""
    if len(wos) > 8:
        more_link = f'<span class="link">View all ({len(wos)}) →</span>'
    html = (
        '<div class="iwo3-panel">'
        '<div class="iwo3-section-head">'
        '<span>Recent Work Orders</span>'
        f'{more_link}'
        '</div>'
        f'{"".join(rows_html)}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def main() -> None:
    _header()
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    api = page_requires_api()
    if api is None:
        return

    try:
        metrics = api.work_order_metrics()
    except APIError as err:
        st.error(f"{err.status_code} — {err.detail}")
        return
    except AttributeError:
        metrics = None

    row1 = st.columns(4)
    row2 = st.columns(4)
    if metrics is None:
        cards: list[tuple[str, str, Optional[str]]] = [
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

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    left, right = st.columns([2, 1])

    with left:
        try:
            wos = api.list_work_orders()
        except APIError as err:
            st.error(f"{err.status_code} — {err.detail}")
            wos = []
        if not wos:
            st.markdown(
                '<div class="iwo3-panel"><div class="iwo3-section-head">Recent Work Orders</div>'
                '<div style="color:#6B7280;font-size:0.86rem;">No work orders in this tenant yet.</div></div>',
                unsafe_allow_html=True,
            )
        else:
            _recent_wo_panel(wos)

    with right:
        st.markdown(
            '<div class="iwo3-section-head"><span>Orchestration</span></div>',
            unsafe_allow_html=True,
        )
        _tier_card(
            "Tier 1 — Aiden", "Policy, Routing, Decisions", "1"
        )
        _tier_card(
            "Tier 1.5 — PM Coordination",
            "Workflow orchestration, Step coordination",
            "1.5",
            variant="t15",
        )
        _tier_card(
            "Tier 2 — Sub-Agents",
            "Aiden-controlled or Independent",
            "2",
            variant="t2",
        )


main()
