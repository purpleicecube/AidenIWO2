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


def _operator_recovery_panel(api, wo: Any) -> None:
    """Loop Xi — Reopen / Edit / Redispatch. Only renders if the WO is
    in a status where at least one of the three actions is legal. Hides
    quietly otherwise so the col_actions panel stays compact for new
    WOs that don't need recovery affordances.

    BUG-060 (2026-05-10): widened `is_active` from ("pending",
    "processing") to include all non-terminal states where operator
    amendment is operationally useful — `blocked`,
    `awaiting_operator`, and `deferred`. Operator-reported trap: a WO
    in `awaiting_operator` (the most likely state for amendment)
    could not be edited without a manual status hop through
    `processing` first. Now in lockstep with backend
    _EDITABLE_STATUSES / _REDISPATCHABLE_STATUSES."""
    is_terminal = wo.status in ("completed", "done", "failed")
    is_active = wo.status in (
        "pending",
        "processing",
        "blocked",
        "awaiting_operator",
        "deferred",
    )
    if not (is_terminal or is_active):
        return

    st.markdown("**Recovery**")

    # Permission preflight — all three actions gate on work_order:update
    # server-side. One check covers all three buttons.
    try:
        decision = api.check_permission("work_order:update")
    except APIError as err:
        st.caption(f"⚠️ perm check failed: {err.detail}")
        return
    if not decision.allowed:
        st.caption(
            f"_Recovery requires `work_order:update` "
            f"(your role: `{decision.role}`)._"
        )
        return

    if is_terminal:
        with st.popover(
            "Reopen", icon=":material/restart_alt:", use_container_width=True
        ):
            st.markdown("**Reopen this work order**")
            st.caption(
                "Moves the WO from terminal back to `processing`. "
                "A reason is required and recorded in the audit trail."
            )
            reason = st.text_area(
                "Reason",
                key=f"reopen-reason-{wo.id}",
                max_chars=500,
                placeholder="e.g., template wrong; needs Klear branding",
            )
            if st.button(
                "Confirm Reopen",
                key=f"reopen-confirm-{wo.id}",
                type="primary",
                disabled=not reason.strip(),
            ):
                with st.spinner("reopening…"):
                    try:
                        result = api.reopen_work_order(
                            wo.id, reason=reason.strip()
                        )
                        st.success(
                            f"✅ Reopened — cycle "
                            f"`{result.get('cycle_id') or '-'}`"
                            + (
                                " · prior assignments cleared"
                                if result.get("cleared_assignments")
                                else ""
                            )
                        )
                        st.rerun()
                    except APIError as err:
                        st.error(f"❌ {err.status_code} — {err.detail}")

    if is_active:
        # Inline edit form. Template dropdown is sourced from the
        # tenant-scoped /template_profiles endpoint so the operator
        # gets explicit selection (improvement over IWO2's prose-only
        # path).
        with st.popover(
            "Edit", icon=":material/edit:", use_container_width=True
        ):
            st.markdown("**Edit this work order**")
            st.caption(
                "Partial update. Only changed fields are written; "
                "blank fields keep their current value."
            )
            new_title = st.text_input(
                "Title",
                value=wo.title,
                max_chars=240,
                key=f"edit-title-{wo.id}",
            )
            new_desc = st.text_area(
                "Description",
                value=wo.description or "",
                max_chars=8000,
                height=140,
                key=f"edit-desc-{wo.id}",
            )
            type_options = (
                "content_brief",
                "deck_build",
                "data_analysis",
                "research",
                "code_change",
                "decision_request",
                "ops_task",
                "general",
            )
            new_type = st.selectbox(
                "Type",
                options=type_options,
                index=(
                    type_options.index(wo.type)
                    if wo.type in type_options
                    else 0
                ),
                key=f"edit-type-{wo.id}",
            )
            priority_options = ("low", "medium", "high", "critical")
            new_priority = st.selectbox(
                "Priority",
                options=priority_options,
                index=(
                    priority_options.index(wo.priority)
                    if wo.priority in priority_options
                    else 1
                ),
                key=f"edit-prio-{wo.id}",
            )
            # Template dropdown — Loop Xi explicit-template upgrade
            # over IWO2. Pulls active tenant-scoped profiles only.
            tp_options = [("(no change)", None)]
            try:
                tps = api.list_template_profiles(status="active")
                for tp in tps:
                    label = (
                        f"{tp.get('profile_key')} · "
                        f"{tp.get('output_kind')}"
                    )
                    tp_options.append((label, tp.get("id")))
            except APIError as err:
                st.caption(
                    f"⚠️ template list unavailable: {err.detail}"
                )
            tp_choice = st.selectbox(
                "Template profile (optional)",
                options=[label for label, _ in tp_options],
                index=0,
                key=f"edit-tp-{wo.id}",
                help=(
                    "Explicit template selection. Improves on IWO2 "
                    "where templates were inferred from description "
                    "prose."
                ),
            )
            tp_id = next(
                (tid for label, tid in tp_options if label == tp_choice),
                None,
            )
            if st.button(
                "Save edits",
                key=f"edit-save-{wo.id}",
                type="primary",
            ):
                payload: dict[str, Any] = {}
                if new_title and new_title != wo.title:
                    payload["title"] = new_title
                if new_desc != (wo.description or ""):
                    payload["description"] = new_desc
                if new_type and new_type != wo.type:
                    payload["type"] = new_type
                if new_priority and new_priority != wo.priority:
                    payload["priority"] = new_priority
                if tp_id is not None:
                    payload["template_profile_id"] = tp_id
                if not payload:
                    st.info("No changes to save.")
                else:
                    with st.spinner("saving…"):
                        try:
                            api.edit_work_order(wo.id, **payload)
                            st.success(
                                f"✅ Saved — fields: "
                                f"{', '.join(sorted(payload.keys()))}"
                            )
                            st.rerun()
                        except APIError as err:
                            st.error(
                                f"❌ {err.status_code} — {err.detail}"
                            )

        # Redispatch — fresh-fire dispatch on the reopened/edited WO.
        if st.button(
            "Redispatch to Aiden",
            key=f"redispatch-{wo.id}",
            help=(
                "Re-fire Aiden Tier 1 → Tier 2/Workflow on the "
                "current WO contents. Use after reopen + edit to "
                "send the revised brief through the pipeline."
            ),
        ):
            with st.spinner("redispatching…"):
                try:
                    r = api.redispatch_work_order(wo.id)
                except APIError as err:
                    st.error(f"❌ {err.status_code} — {err.detail}")
                    r = None
            if r:
                if r.get("ok"):
                    kind = r.get("decision_kind") or "redispatched"
                    st.success(f"✅ {kind}")
                    st.rerun()
                elif r.get("decision_kind") == "clarification":
                    st.warning(
                        "❓ Aiden asked: "
                        f"{r.get('clarification_question')}"
                    )
                else:
                    st.warning(f"⚠️ {r.get('error')}")


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

                # BUG-067 — operator-controlled advance of a multi-step
                # workflow_brief chain. The background workflow_step_worker
                # advances pending step_runs every 10s automatically; this
                # button is for operators who want to step through manually
                # (mid-chain inspection, debugging, or to fire a step before
                # the next worker tick). Shows for any WO in `processing`;
                # the route returns 404 with a friendly hint when the WO
                # has no running workflow_execution (e.g. single-step
                # `work_order_brief` dispatches).
                if st.button(
                    "Run next step",
                    key=f"advance-step-{wo.id}",
                    help=(
                        "Advance the next pending step in this WO's "
                        "running workflow chain. Returns the step "
                        "outcome and whether more steps remain. The "
                        "background worker also advances pending steps "
                        "every ~10s without operator action."
                    ),
                ):
                    with st.spinner("running next step…"):
                        try:
                            r = api.run_next_workflow_step_by_wo(wo.id)
                        except APIError as err:
                            if err.status_code == 404:
                                d = err.detail or {}
                                st.info(
                                    f"⏸ {d.get('hint', d)}"
                                )
                            else:
                                st.error(
                                    f"❌ {err.status_code} — {err.detail}"
                                )
                            r = None
                    if r:
                        if r.get("ok"):
                            if r.get("workflow_finished"):
                                st.success(
                                    "✅ workflow finished — all steps "
                                    "complete"
                                )
                            else:
                                pkg_id = r.get("output_package_id")
                                pkg_suffix = (
                                    f" → output_package `{pkg_id}`"
                                    if pkg_id else ""
                                )
                                st.success(
                                    f"✅ advanced `{r.get('step_key')}` "
                                    f"(step_run `{r.get('step_run_id')}`)"
                                    f"{pkg_suffix}"
                                )
                            st.rerun()
                        else:
                            st.warning(f"⚠️ {r.get('error')}")

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

                # Loop Xi — operator recovery panel. Renders Reopen on
                # terminal WOs and Edit + Redispatch on active WOs.
                _operator_recovery_panel(api, wo)

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
