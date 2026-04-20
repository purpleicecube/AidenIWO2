"""IWO3 Console — Handoffs + Candidate Review page.

Lists handoffs grouped by `candidate_group_id`. For candidate
handoffs, exposes Select + Reject buttons (disabled when the current
user lacks `output_candidate:select` / `output_candidate:reject`).
Non-candidate handoffs render as a plain list.
"""

from __future__ import annotations

from collections import defaultdict
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
        page_title="IWO3 Console — Handoffs",
        page_icon="🎯",
        layout="wide",
    )
    st.title("Output Handoffs + Candidate Review")

    api = _api()
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
        f"**Your role:** `{can_select.role or 'none'}` — "
        f"select={'✅' if can_select.allowed else '❌'} "
        f"reject={'✅' if can_reject.allowed else '❌'}"
    )

    # Candidate groups
    by_group: dict[str, list] = defaultdict(list)
    ungrouped = []
    for h in handoffs:
        if h.candidate_group_id:
            by_group[h.candidate_group_id].append(h)
        else:
            ungrouped.append(h)

    if by_group:
        st.subheader("Candidate groups")
        for group_id, members in by_group.items():
            with st.expander(
                f"Group `{group_id[:8]}…` — {len(members)} handoff(s)",
                expanded=any(m.candidate_status == "candidate" for m in members),
            ):
                for h in members:
                    cols = st.columns([3, 1, 1])
                    with cols[0]:
                        st.markdown(
                            f"- `{h.id[:8]}…` — status `{h.status}` — "
                            f"candidate `{h.candidate_status}`"
                        )
                    with cols[1]:
                        disabled = not can_select.allowed or h.candidate_status != "candidate"
                        if st.button(
                            "Select",
                            key=f"sel-{h.id}",
                            disabled=disabled,
                            help=(
                                None
                                if can_select.allowed
                                else f"Denied — needs output_candidate:select"
                            ),
                        ):
                            try:
                                api.select_candidate(h.id)
                                st.success(f"Selected {h.id[:8]}…; siblings auto-rejected.")
                                st.rerun()
                            except APIError as err:
                                st.error(f"❌ {err.status_code} — {err.detail}")
                    with cols[2]:
                        disabled = not can_reject.allowed or h.candidate_status != "candidate"
                        if st.button(
                            "Reject",
                            key=f"rej-{h.id}",
                            disabled=disabled,
                            help=(
                                None
                                if can_reject.allowed
                                else f"Denied — needs output_candidate:reject"
                            ),
                        ):
                            try:
                                api.reject_candidate(h.id)
                                st.success(f"Rejected {h.id[:8]}….")
                                st.rerun()
                            except APIError as err:
                                st.error(f"❌ {err.status_code} — {err.detail}")

    if ungrouped:
        st.subheader("Non-candidate handoffs")
        for h in ungrouped:
            st.markdown(
                f"- `{h.id[:8]}…` — status `{h.status}` — "
                f"package `{(h.output_package_id or '—')[:8]}…`"
            )


if __name__ == "__main__":
    main()
