"""Handoffs + Candidate Review — Loop δ.7 polish.

Reviewer-gated Select / Reject actions for output handoffs. Latest-
first ordering; clearer status chip; package title visible in the
list (was just an opaque uuid prefix); helpful empty state.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


_STATUS_EMOJI = {
    "queued": "🟡",
    "submitted": "🔵",
    "accepted": "🟢",
    "completed": "🟢",
    "failed": "❌",
    "cancelled": "⚫",
}


def _status_chip(status: str) -> str:
    return f"{_STATUS_EMOJI.get(status, '⚫')} `{status}`"


def _ts(value: Optional[str]) -> str:
    if not value:
        return "-"
    return value.replace("T", " ").replace("+00:00", " UTC")


def main() -> None:
    st.markdown(
        '<h2 style="margin:0 0 4px 0; font-size:1.5rem; font-weight:700;">Handoffs &amp; Candidate Review</h2>'
        '<div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">'
        'Reviewer-gated select / reject for output handoffs. Latest first.'
        '</div>',
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        handoffs = api.list_output_handoffs()
        packages = api.list_output_packages()
        can_select = api.check_permission("output_candidate:select")
        can_reject = api.check_permission("output_candidate:reject")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    pkg_titles: dict[str, str] = {p.id: p.title for p in packages}

    if not handoffs:
        st.info(
            "No handoffs in this tenant yet. Handoffs are created when "
            "an output package is submitted to an external adapter "
            "(Gamma, etc). Try Submit Order or Chat with Aiden, then "
            "dispatch the resulting work order."
        )
        return

    cols = st.columns([1, 1, 1, 1])
    cols[0].metric("Handoffs", len(handoffs))
    cols[1].metric(
        "Pending review",
        sum(1 for h in handoffs if h.candidate_status == "candidate"),
    )
    cols[2].metric(
        "Sent",
        sum(1 for h in handoffs if h.status in {"submitted", "accepted", "completed"}),
    )
    cols[3].metric(
        "Failed",
        sum(1 for h in handoffs if h.status == "failed"),
    )

    st.caption(
        f"**Your role:** `{can_select.role or 'none'}` · "
        f"select={'✅' if can_select.allowed else '❌'} · "
        f"reject={'✅' if can_reject.allowed else '❌'}"
    )

    groups: dict[str, list] = defaultdict(list)
    ungrouped = []
    for h in handoffs:
        if h.candidate_group_id:
            groups[h.candidate_group_id].append(h)
        else:
            ungrouped.append(h)

    # Sort ungrouped latest-first; group dict ordered by latest member.
    ungrouped_sorted = sorted(
        ungrouped, key=lambda h: (h.created_at or "", h.id), reverse=True
    )

    if groups:
        st.markdown("### Candidate groups")
        for group_id, members in groups.items():
            members_sorted = sorted(
                members, key=lambda m: (m.created_at or "", m.id), reverse=True
            )
            pending = any(m.candidate_status == "candidate" for m in members)
            with st.expander(
                f"Group `{group_id[:8]}…` · {len(members)} handoff(s)"
                + (" · ⚠️ pending review" if pending else ""),
                expanded=pending,
            ):
                for h in members_sorted:
                    title = pkg_titles.get(h.output_package_id or "", "—")
                    cols = st.columns([3, 1, 1])
                    cols[0].markdown(
                        f"- **{title}** · {_status_chip(h.status)} · "
                        f"candidate `{h.candidate_status}` · "
                        f"created {_ts(h.created_at)}"
                    )
                    disabled_sel = not can_select.allowed or h.candidate_status != "candidate"
                    disabled_rej = not can_reject.allowed or h.candidate_status != "candidate"
                    if cols[1].button("Select", key=f"sel-{h.id}", disabled=disabled_sel):
                        try:
                            api.select_candidate(h.id)
                            st.success(
                                f"Selected — siblings auto-rejected."
                            )
                            st.rerun()
                        except APIError as err:
                            st.error(f"❌ {err.detail}")
                    if cols[2].button("Reject", key=f"rej-{h.id}", disabled=disabled_rej):
                        try:
                            api.reject_candidate(h.id)
                            st.success("Rejected.")
                            st.rerun()
                        except APIError as err:
                            st.error(f"❌ {err.detail}")

    if ungrouped_sorted:
        st.markdown("### All handoffs")
        for h in ungrouped_sorted:
            title = pkg_titles.get(h.output_package_id or "", "—")
            extras = []
            if h.external_destination:
                extras.append(f"destination `{h.external_destination}`")
            if h.external_reference:
                extras.append(f"ref `{h.external_reference}`")
            extra_line = " · ".join(extras)
            st.markdown(
                f"- **{title}** · {_status_chip(h.status)} · "
                f"package `{(h.output_package_id or '—')[:8]}…` · "
                f"created {_ts(h.created_at)}"
                + (f"\n  {extra_line}" if extra_line else "")
            )


main()
