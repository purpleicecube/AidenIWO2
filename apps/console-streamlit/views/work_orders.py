"""Work Orders — IWO3 Console.

List + detail + transitions. Each transition button preflights the
required permission via /permissions/check so role-denied actions
render disabled with a "requires X" tooltip; the server-side
requirePermission is still the authoritative gate.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import streamlit as st

from api_client import APIError
from shell import page_requires_api


SAFE_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["processing", "cancelled", "deferred"],
    "processing": ["completed", "blocked", "awaiting_operator", "failed", "cancelled"],
    "blocked": ["processing", "cancelled", "failed"],
    "awaiting_operator": ["processing", "cancelled", "failed"],
    "deferred": ["processing", "cancelled"],
    "completed": ["processing"],
    "done": ["processing"],
    "failed": ["processing"],
    "cancelled": [],
}


PERM_FOR_TRANSITION: dict[str, str] = {
    "processing": "work_order:submit",
    "completed": "work_order:update",
    "done": "work_order:update",
    "blocked": "work_order:update",
    "awaiting_operator": "work_order:update",
    "failed": "work_order:update",
    "cancelled": "work_order:cancel",
    "deferred": "work_order:update",
}


def _ts(ts: str | None) -> str:
    if not ts:
        return "-"
    return ts.replace("T", " ").replace("+00:00", " UTC")


def _metadata_work_order_id(metadata: dict[str, Any]) -> str | None:
    return (
        metadata.get("workOrderId")
        or metadata.get("work_order_id")
        or metadata.get("work_orderId")
    )


def _audit_summary(action: str, metadata: dict[str, Any]) -> str:
    if action == "llm.invoked":
        role = metadata.get("agentRole") or "unknown-role"
        decision = metadata.get("decisionKind") or "decision"
        provider = metadata.get("provider") or "unknown-provider"
        model = metadata.get("model") or "unknown-model"
        total = metadata.get("totalTokens")
        token_note = f" ({total} tokens)" if total else ""
        return (
            f"{role} via {provider}/{model} produced `{decision}`{token_note}."
        )
    if action == "llm.failed":
        role = metadata.get("agentRole") or "unknown-role"
        kind = metadata.get("kind") or "failure"
        detail = metadata.get("detail") or "No detail recorded."
        return f"{role} failed with `{kind}`: {detail}"
    if action == "workflow_execution.started":
        template = metadata.get("templateKey") or "unknown-template"
        steps = metadata.get("stepCount")
        step_note = f" with {steps} planned steps" if steps else ""
        return f"PM started workflow `{template}`{step_note}."
    if action == "output_package.created":
        kind = metadata.get("outputKind") or "output"
        title = metadata.get("title") or "Untitled package"
        return f"Created output package `{title}` of kind `{kind}`."
    if action.startswith("adapter_dispatch."):
        handoff_id = metadata.get("handoffId") or "-"
        external = metadata.get("externalReference") or "-"
        stage = action.removeprefix("adapter_dispatch.")
        return (
            f"Adapter handoff `{handoff_id}` is `{stage}`"
            f" (external ref: `{external}`)."
        )
    if action == "work_order.transitioned":
        return (
            f"Work order moved to `{metadata.get('to') or '-'}`"
            f" from `{metadata.get('from') or '-'}`."
        )
    reason = metadata.get("reason")
    if reason:
        return reason
    return "Raw audit metadata available below."


def _group_audit_rows(rows: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        wo_id = row.target_id if row.target_type == "work_order" else None
        if not wo_id:
            wo_id = _metadata_work_order_id(row.metadata)
        if wo_id:
            grouped[wo_id].append(row)
    return grouped


_STATUS_EMOJI = {
    "pending": "🟡",
    "processing": "🔵",
    "blocked": "🔴",
    "awaiting_operator": "🟠",
    "deferred": "⚪",
    "completed": "🟢",
    "done": "🟢",
    "failed": "❌",
    "cancelled": "⚫",
}


def _state_chip(status: str) -> str:
    return f"{_STATUS_EMOJI.get(status, '⚫')} `{status}`"


def _status_chip_class(status: str) -> str:
    if status in ("completed", "done"):
        return "iwo3-chip green"
    if status == "reopened":
        return "iwo3-chip violet"
    if status in ("deferred",):
        return "iwo3-chip sky"
    if status in ("cancelled", "archived"):
        return "iwo3-chip gray"
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


def _status_chip_html(status: str) -> str:
    label = status.replace("_", " ")
    emoji = _STATUS_EMOJI.get(status, "⚫")
    return (
        f'<span class="{_status_chip_class(status)}">'
        f"<span>{emoji}</span>{label}</span>"
    )


def _priority_chip_html(priority: str) -> str:
    return (
        f'<span class="{_priority_chip_class(priority)}">'
        f"{priority}</span>"
    )


def _aiden_decision_card(audit_rows: list[Any]) -> None:
    """Surface the most recent Aiden Tier-1 decision at the top of the
    Lifecycle tab so operators can see what Aiden chose without reading
    every row. Returns silently if no Aiden invocation exists yet."""
    aiden = next(
        (
            r for r in audit_rows
            if r.action == "llm.invoked"
            and (r.metadata.get("agentRole") or "").startswith("aiden_")
        ),
        None,
    )
    if aiden is None:
        return
    md = aiden.metadata
    decision = md.get("decisionKind") or "(unknown)"
    provider = md.get("provider") or "-"
    model = md.get("model") or "-"
    tokens = md.get("totalTokens")
    latency = md.get("latencyMs")
    st.markdown("**Aiden decided**")
    st.markdown(
        f"`{decision}` via **{provider}** / `{model}`"
        + (f" · {latency}ms" if latency else "")
        + (f" · {tokens} tokens" if tokens else "")
    )


def _render_lifecycle(wo: Any, audit_rows: list[Any]) -> None:
    if not audit_rows:
        st.caption("No audit evidence yet for this work order.")
        return

    _aiden_decision_card(audit_rows)
    st.markdown(
        " ".join(
            [
                "**Current state:**",
                _status_chip_html(wo.status),
                "&nbsp;&nbsp;**Priority:**",
                _priority_chip_html(wo.priority),
            ]
        ),
        unsafe_allow_html=True,
    )

    st.markdown("**What happened**")
    for row in audit_rows[:6]:
        st.markdown(
            f"- `{_ts(row.created_at)}` · **{row.action}** — "
            f"{_audit_summary(row.action, row.metadata)}"
        )

    latest_invocation = next(
        (row for row in audit_rows if row.action == "llm.invoked"), None
    )
    if latest_invocation is not None:
        md = latest_invocation.metadata
        stats = [
            ("Latest role", md.get("agentRole") or "-"),
            ("Decision/output", md.get("decisionKind") or "-"),
            ("Provider", md.get("provider") or "-"),
            ("Tokens", str(md.get("totalTokens") or "-")),
        ]
        stat_html = "".join(
            (
                '<div class="iwo3-stat">'
                f'<div class="k">{label}</div>'
                f'<div class="v">{value}</div>'
                "</div>"
            )
            for label, value in stats
        )
        st.markdown(
            f'<div class="iwo3-stat-strip">{stat_html}</div>',
            unsafe_allow_html=True,
        )


def _render_outputs(packages: list[Any], handoffs_by_package: dict[str, list[Any]]) -> None:
    if not packages:
        st.caption("No output packages have been created for this work order yet.")
        return

    for pkg in packages:
        st.markdown(
            f"**{pkg.title}** · `{pkg.output_kind}` · `{pkg.status}`"
        )
        st.caption(f"Package `{pkg.id}` · created {_ts(pkg.created_at)}")
        handoffs = handoffs_by_package.get(pkg.id, [])
        if not handoffs:
            st.caption("No handoffs linked to this package yet.")
            continue
        for handoff in handoffs:
            st.markdown(
                f"- Handoff `{handoff.id}` · status `{handoff.status}` · "
                f"candidate `{handoff.candidate_status}`"
            )
            extra = []
            if handoff.external_destination:
                extra.append(f"destination `{handoff.external_destination}`")
            if handoff.external_reference:
                extra.append(f"external ref `{handoff.external_reference}`")
            if handoff.created_at:
                extra.append(f"created {_ts(handoff.created_at)}")
            if extra:
                st.caption(" · ".join(extra))


def _render_audit_panel(wo_id: str, audit_rows: list[Any]) -> None:
    if st.button("Open full Audit Log page", key=f"audit-page-{wo_id}"):
        st.session_state["audit_log_work_order_filter"] = wo_id
        st.switch_page("views/audit_log.py")

    if not audit_rows:
        st.caption("No audit rows recorded yet.")
        return

    for row in audit_rows:
        with st.expander(
            f"{_ts(row.created_at)} · {row.action}",
            expanded=False,
        ):
            st.markdown(_audit_summary(row.action, row.metadata))
            st.markdown(
                f"**Target:** `{row.target_type or '-'} / {row.target_id or '-'}`"
            )
            st.code(
                json.dumps(row.metadata, indent=2, default=str),
                language="json",
            )


def _transition_button(api, wo_id: str, from_status: str, to_status: str) -> None:
    perm = PERM_FOR_TRANSITION.get(to_status, "work_order:update")
    try:
        decision = api.check_permission(perm)
    except APIError as err:
        st.caption(f"⚠️ perm check failed: {err.detail}")
        return
    label = f"→ {to_status}"
    if decision.allowed:
        if st.button(label, key=f"btn-{wo_id}-{to_status}"):
            try:
                result = api.transition_work_order(wo_id, to_status)
                st.success(
                    f"Transitioned {from_status} → {result['to']} (event: `{result['event']}`)"
                )
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")
    else:
        st.button(
            label,
            key=f"btn-{wo_id}-{to_status}",
            disabled=True,
            help=f"Denied — requires `{perm}` (your role: `{decision.role}`)",
        )


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Work Orders</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Tenant-scoped work orders with role-aware transition actions.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        wos = api.list_work_orders()
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    try:
        all_packages = api.list_output_packages()
    except APIError:
        all_packages = []

    try:
        all_handoffs = api.list_output_handoffs()
    except APIError:
        all_handoffs = []

    audit_allowed = False
    audit_rows: list[Any] = []
    try:
        if api.check_permission("audit_log:read").allowed:
            audit_allowed = True
            audit_rows = api.list_audit_log(limit=300)
    except APIError:
        audit_allowed = False
        audit_rows = []

    packages_by_wo: dict[str, list[Any]] = defaultdict(list)
    for pkg in all_packages:
        if pkg.work_order_id:
            packages_by_wo[pkg.work_order_id].append(pkg)

    handoffs_by_package: dict[str, list[Any]] = defaultdict(list)
    for handoff in all_handoffs:
        if handoff.output_package_id:
            handoffs_by_package[handoff.output_package_id].append(handoff)

    audit_by_wo = _group_audit_rows(audit_rows)

    if not wos:
        st.info("No work orders in this tenant yet.")
        if st.button("＋ Create one"):
            st.switch_page("views/submit_order.py")
        return

    statuses = sorted({wo.status for wo in wos})
    status_filter = st.multiselect("Status", options=statuses, default=statuses)

    # Optional focus from chat → "Open Work Order" or from output_packages.
    # Loop Iota.x — also accept ?focus=<id> from the URL so the Dashboard
    # Recent Work Orders rows can deep-link directly. session_state wins
    # if both are present (chat handoff is more explicit than URL).
    focus_id = st.session_state.pop("work_orders_focus_id", None)
    if not focus_id:
        qp_focus = st.query_params.get("focus")
        if isinstance(qp_focus, str) and qp_focus.strip():
            focus_id = qp_focus.strip()
            # Clear the param so a refresh doesn't re-pin focus indefinitely.
            try:
                del st.query_params["focus"]
            except KeyError:
                pass
    if focus_id:
        st.info(
            "Showing the work order opened from another surface. The expander "
            "is open by default; clear status filters above if it doesn't "
            "appear (it may be in a status you've filtered out)."
        )

    # Sort newest first so chat-created WOs surface at the top.
    def _sort_key(wo):
        return (wo.created_at or "", wo.id)

    wos_sorted = sorted(wos, key=_sort_key, reverse=True)
    filtered = [wo for wo in wos_sorted if wo.status in status_filter]
    st.caption(f"Showing {len(filtered)} / {len(wos)} work orders (latest first)")

    for wo in filtered:
        is_focused = bool(focus_id and wo.id == focus_id)
        with st.expander(
            f"**{wo.title}** — {_state_chip(wo.status)} · priority `{wo.priority}`",
            expanded=is_focused,
        ):
            st.markdown(
                f"{_status_chip_html(wo.status)} &nbsp;&nbsp; {_priority_chip_html(wo.priority)}",
                unsafe_allow_html=True,
            )
            col_meta, col_actions = st.columns([2, 1])
            with col_meta:
                st.markdown(f"**ID:** `{wo.id}`")
                st.markdown(f"**Type:** `{wo.type}`")
                st.markdown(f"**Submitted by:** `{wo.submitted_by_user_id or '-'}`")
                if wo.description:
                    st.markdown(f"**Description:** {wo.description}")
                if wo.correlation_id:
                    st.markdown(f"**Correlation:** `{wo.correlation_id}`")
                st.markdown(f"**Created:** {_ts(wo.created_at)}")
                st.markdown(f"**Updated:** {_ts(wo.updated_at)}")
            with col_actions:
                st.markdown("**Dispatch**")
                if st.button(
                    "Run Aiden + Tier 2",
                    key=f"dispatch-{wo.id}",
                    help=(
                        "Aiden Tier 1 classifies; if work_order_brief, "
                        "Tier 2 produces the deliverable; if "
                        "workflow_brief, PM Tier 1.5 instantiates the "
                        "workflow."
                    ),
                ):
                    with st.spinner("dispatching…"):
                        try:
                            r = api.dispatch_work_order(wo.id)
                        except APIError as err:
                            st.error(
                                f"❌ {err.status_code} — {err.detail}"
                            )
                            r = None
                    if r:
                        if r.get("ok"):
                            kind = r.get("decision_kind")
                            if kind == "work_order_brief":
                                st.success(
                                    f"✅ {kind} → output_package "
                                    f"`{r.get('output_package_id')}`"
                                )
                            elif kind == "workflow_brief":
                                st.success(
                                    f"✅ {kind} → execution "
                                    f"`{r.get('workflow_execution_id')}` "
                                    f"({len(r.get('step_run_ids') or [])} steps)"
                                )
                            else:
                                st.success(f"✅ {kind}")
                            st.rerun()
                        else:
                            if r.get("decision_kind") == "clarification":
                                st.warning(
                                    "❓ Aiden asked: "
                                    f"{r.get('clarification_question')}"
                                )
                            else:
                                st.warning(
                                    f"⚠️ {r.get('error')}"
                                )

                if st.button(
                    "Render via Gamma",
                    key=f"render-{wo.id}",
                    help=(
                        "One-shot dispatch of this WO's latest "
                        "gamma_*-kinded output_package to Gamma. "
                        "Use after Tier 2 has produced the package "
                        "but the auto-dispatch hook didn't fire (or "
                        "to retry a failed dispatch). The poll worker "
                        "advances the rest; the WO auto-completes "
                        "when the handoff lands."
                    ),
                ):
                    with st.spinner("submitting to Gamma…"):
                        try:
                            r = api.render_work_order(wo.id)
                        except APIError as err:
                            if err.status_code == 404:
                                st.warning(
                                    "No gamma_*-kinded output_package on "
                                    "this WO yet — run Aiden + Tier 2 first."
                                )
                            elif err.status_code == 409:
                                d = err.detail or {}
                                st.info(
                                    f"⏸ A handoff is already in flight for "
                                    f"this package. {d}"
                                )
                            else:
                                st.error(
                                    f"❌ {err.status_code} — {err.detail}"
                                )
                            r = None
                    if r:
                        if r.get("ok"):
                            handoff = r.get("handoff_id")
                            ext_ref = r.get("external_reference")
                            st.success(
                                f"✅ submitted to Gamma — handoff "
                                f"`{handoff}` (gamma generation "
                                f"`{ext_ref}`). Poll worker will advance."
                            )
                            st.rerun()
                        else:
                            st.warning(f"⚠️ {r.get('error')}")

                st.markdown("**Transitions**")
                legal = SAFE_TRANSITIONS.get(wo.status, [])
                if not legal:
                    st.caption(f"_Terminal — no transitions out of `{wo.status}`._")
                for target in legal:
                    _transition_button(api, wo.id, wo.status, target)

            related_audit = audit_by_wo.get(wo.id, [])
            related_packages = packages_by_wo.get(wo.id, [])
            tabs = st.tabs(["Lifecycle", "Outputs", "Audit"])
            with tabs[0]:
                _render_lifecycle(wo, related_audit)
            with tabs[1]:
                _render_outputs(related_packages, handoffs_by_package)
            with tabs[2]:
                if audit_allowed:
                    _render_audit_panel(wo.id, related_audit)
                else:
                    st.caption(
                        "Audit details are available on the Audit Log page for "
                        "roles that hold `audit_log:read`."
                    )


main()
