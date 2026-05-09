"""Loop Kappa — Memory V1.5 ops health view.

Operator surface for the firewall smoke alarm
(`memory.source_rejected`) plus assembly-quality signals from the
Loop Iota audit vocabulary:

  - `memory.source_rejected` last-24h cardinality (M-009 P0 gate)
  - `memory.bypassed` reasons distribution
  - `memory.budget_truncated` truncated_kinds frequency

This is read-only diagnostics. No mutation; no admin-only path —
visible to anyone who can read `audit_log:read` (operator role and
above).
"""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def _fetch_audit_window(api, *, hours: int = 24) -> list[dict]:
    """Pull recent action_audit_log rows via /audit_log. Memory events
    are tenant-scoped, so the ops surface only sees the active tenant's
    rows — by design.
    """
    try:
        data = api._request(
            "GET",
            "/audit_log",
            params={"limit": 500, "hours": hours},
        )
        return data.get("rows", []) if isinstance(data, dict) else []
    except APIError as exc:
        st.error(f"audit log unreachable: {exc.detail}")
        return []


def _bucket_memory_events(rows: list[dict]) -> dict:
    rejected: list[dict] = []
    bypassed_reasons: dict[str, int] = {}
    truncated_kinds: dict[str, int] = {}
    applied_count = 0

    for r in rows:
        event = r.get("event") or r.get("action") or ""
        meta = r.get("metadata") or {}
        if event == "memory.source_rejected":
            rejected.append(r)
        elif event == "memory.bypassed":
            reason = meta.get("reason", "(unknown)")
            bypassed_reasons[reason] = bypassed_reasons.get(reason, 0) + 1
        elif event == "memory.budget_truncated":
            kinds = meta.get("truncated_kinds") or []
            for k in kinds:
                truncated_kinds[k] = truncated_kinds.get(k, 0) + 1
        elif event == "memory.applied":
            applied_count += 1
    return {
        "rejected": rejected,
        "bypassed_reasons": bypassed_reasons,
        "truncated_kinds": truncated_kinds,
        "applied_count": applied_count,
    }


def main() -> None:
    page_requires_api()
    api = st.session_state["iwo3_api"]
    tenant_label = st.session_state.get("iwo3_current_tenant_label", "this tenant")

    st.markdown("# Memory Health")
    st.caption(
        f"Last-24h memory assembly diagnostics for **{tenant_label}**. "
        "The `source_rejected` count is the Loop Iota M-009 firewall "
        "smoke alarm — operationally a P0 incident if non-zero."
    )

    rows = _fetch_audit_window(api, hours=24)
    bucket = _bucket_memory_events(rows)

    # Headline cards.
    cols = st.columns(4)
    with cols[0]:
        st.metric("memory.applied", bucket["applied_count"])
    with cols[1]:
        rejected_count = len(bucket["rejected"])
        st.metric(
            "source_rejected",
            rejected_count,
            help=(
                "Firewall smoke alarm. M-009 in the Loop Iota risk "
                "register treats any non-zero count as a P0 incident."
            ),
        )
        if rejected_count > 0:
            st.error(f"⚠️ {rejected_count} firewall rejection(s) — investigate.")
    with cols[2]:
        st.metric("bypassed", sum(bucket["bypassed_reasons"].values()))
    with cols[3]:
        st.metric("truncated events", sum(bucket["truncated_kinds"].values()))

    # Source rejection detail.
    if bucket["rejected"]:
        st.markdown("### Rejected sources (P0 — investigate each)")
        for r in bucket["rejected"]:
            meta = r.get("metadata") or {}
            with st.container(border=True):
                st.write(
                    f"**{meta.get('kind', '?')}** · "
                    f"reason: `{meta.get('reason', '?')}` · "
                    f"actual_client: `{meta.get('actual_client_id', '?')}` · "
                    f"expected_client: `{meta.get('expected_client_id', '?')}`"
                )
                st.caption(f"emitted {r.get('created_at', '')}")

    # Bypass reason distribution.
    if bucket["bypassed_reasons"]:
        st.markdown("### Bypass reasons")
        for reason, count in sorted(
            bucket["bypassed_reasons"].items(), key=lambda kv: -kv[1]
        ):
            st.write(f"- `{reason}` — {count}")
    else:
        st.caption("_No memory.bypassed events in the last 24h._")

    # Truncation distribution.
    if bucket["truncated_kinds"]:
        st.markdown("### Truncated source kinds (budget pressure)")
        for kind, count in sorted(
            bucket["truncated_kinds"].items(), key=lambda kv: -kv[1]
        ):
            st.write(f"- `{kind}` — {count}")
    else:
        st.caption("_No memory.budget_truncated events in the last 24h._")

    st.divider()
    st.caption(
        "Authority: ADR-031 (Memory V1) firewall Layer 4 + ADR-032 "
        "(Memory V1.5 path-targeted retrieval + canonical facts table)."
    )


main()
