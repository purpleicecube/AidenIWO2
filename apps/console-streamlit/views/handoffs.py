"""Handoffs + Candidate Review — reviewer-gated Select / Reject actions."""

from __future__ import annotations

from collections import defaultdict

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def main() -> None:
    st.markdown("## 🎯 Handoffs & Candidate Review")

    api = page_requires_api()
    if api is None:
        return

    try:
        handoffs = api.list_output_handoffs()
        can_select = api.check_permission("output_candidate:select")
        can_reject = api.check_permission("output_candidate:reject")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not handoffs:
        st.info("No handoffs in this tenant yet.")
        return

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

    if groups:
        st.markdown("### Candidate groups")
        for group_id, members in groups.items():
            with st.expander(
                f"Group `{group_id[:8]}…` · {len(members)} handoff(s)",
                expanded=any(m.candidate_status == "candidate" for m in members),
            ):
                for h in members:
                    cols = st.columns([3, 1, 1])
                    cols[0].markdown(
                        f"- `{h.id[:8]}…` — status `{h.status}` · candidate `{h.candidate_status}`"
                    )
                    disabled_sel = not can_select.allowed or h.candidate_status != "candidate"
                    disabled_rej = not can_reject.allowed or h.candidate_status != "candidate"
                    if cols[1].button("Select", key=f"sel-{h.id}", disabled=disabled_sel):
                        try:
                            api.select_candidate(h.id)
                            st.success(f"Selected {h.id[:8]}…; siblings auto-rejected.")
                            st.rerun()
                        except APIError as err:
                            st.error(f"❌ {err.detail}")
                    if cols[2].button("Reject", key=f"rej-{h.id}", disabled=disabled_rej):
                        try:
                            api.reject_candidate(h.id)
                            st.success(f"Rejected {h.id[:8]}….")
                            st.rerun()
                        except APIError as err:
                            st.error(f"❌ {err.detail}")

    if ungrouped:
        st.markdown("### Non-candidate handoffs")
        for h in ungrouped:
            st.markdown(
                f"- `{h.id[:8]}…` — status `{h.status}` · package `{(h.output_package_id or '—')[:8]}…`"
            )


main()
