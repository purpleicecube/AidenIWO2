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


# Inline-SVG icon set for KPI cards — Lucide/Feather-style strokes,
# 18×18 inside a 32×32 tinted rounded-square (see `.iwo3-metric .icon`
# in shell.py CSS). Streamlit's `:material/*:` syntax cannot render
# inside raw HTML, so we embed the SVG directly.
def _svg(paths: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )


ICON_SVG: dict[str, str] = {
    # grid/layers — "total"
    "total": _svg(
        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/>'
        '<rect x="14" y="14" width="7" height="7" rx="1"/>'
    ),
    "clock": _svg(
        '<circle cx="12" cy="12" r="9"/>'
        '<polyline points="12 7 12 12 15 14"/>'
    ),
    "check": _svg(
        '<circle cx="12" cy="12" r="9"/>'
        '<polyline points="8 12 11 15 16 9"/>'
    ),
    "refresh": _svg(
        '<polyline points="21 3 21 9 15 9"/>'
        '<path d="M20.49 15A9 9 0 1 1 18.54 7.54L21 10"/>'
    ),
    "user": _svg(
        '<circle cx="12" cy="8" r="4"/>'
        '<path d="M4 21a8 8 0 0 1 16 0"/>'
    ),
    "alert": _svg(
        '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/>'
        '<line x1="12" y1="9" x2="12" y2="13"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    "calendar": _svg(
        '<rect x="3" y="4" width="18" height="17" rx="2"/>'
        '<line x1="3" y1="9" x2="21" y2="9"/>'
        '<line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/>'
    ),
    "archive": _svg(
        '<rect x="2" y="3" width="20" height="5" rx="1"/>'
        '<path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/>'
        '<line x1="10" y1="13" x2="14" y2="13"/>'
    ),
}

# label → (tint, svg-name) — colors per Darrel's R-015 mapping:
# Total blue, Pending blue (clock), Completed green, Reopened violet,
# Awaiting Operator violet (user), Blocked amber (warning), Deferred
# sky-blue (calendar), Archived gray.
METRIC_ICONS: dict[str, tuple[str, str]] = {
    "Total": ("blue", "total"),
    "Pending": ("blue", "clock"),
    "Completed": ("green", "check"),
    "Reopened": ("violet", "refresh"),
    "Awaiting Operator": ("violet", "user"),
    "Blocked": ("amber", "alert"),
    "Deferred": ("skyblue", "calendar"),
    "Archived": ("gray", "archive"),
}


def _metric_card(label: str, value: str, hint: Optional[str] = None) -> None:
    tint, svg_name = METRIC_ICONS.get(label, ("gray", "total"))
    svg = ICON_SVG[svg_name]
    hint_html = f'<div class="hint">{escape(hint)}</div>' if hint else ""
    # Flat HTML (no leading whitespace) — see _recent_wo_panel docstring
    # for the indented-code-block parsing caveat.
    html = (
        '<div class="iwo3-metric">'
        f'<div class="header"><div class="label">{escape(label)}</div>'
        f'<div class="icon {tint}">{svg}</div></div>'
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
    html = (
        '<div class="iwo3-panel">'
        '<div class="iwo3-section-head">'
        '<span>Recent Work Orders</span>'
        '</div>'
        f'{"".join(rows_html)}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)
    if st.button(
        f"View all work orders ({len(wos)}) →",
        key="dash-view-all-wos",
    ):
        st.switch_page("views/work_orders.py")


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

    c = metrics.by_status
    # Richer per-status aggregates (e.g. granular deferred/awaiting
    # counters) may be added in Loop 9+; for now we read what the
    # `GET /work_orders/metrics` route returns and default missing
    # statuses to 0 so the cards stay polished.
    cards: list[tuple[str, str, Optional[str]]] = [
        ("Total", str(metrics.total), "All work orders"),
        ("Pending", str(c.get("pending", 0)), "Awaiting Aiden review"),
        ("Completed", str(c.get("completed", 0) + c.get("done", 0)), "Successfully processed"),
        ("Reopened", str(metrics.reopened_count), "Sent back for revision"),
        ("Awaiting Operator", str(c.get("awaiting_operator", 0)), "Independent sub-agents"),
        ("Blocked", str(c.get("blocked", 0)), "Requires attention"),
        ("Deferred", str(c.get("deferred", 0)), "Decision postponed"),
        ("Archived", str(c.get("cancelled", 0)), "Removed from active view"),
    ]
    row1 = st.columns(4)
    row2 = st.columns(4)
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
