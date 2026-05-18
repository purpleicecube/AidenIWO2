"""Submit Order — create a new Work Order.

Beta-2 phase 0.1 (2026-04-30) — extends the Loop 8.3 form with optional
output_kind + template_profile selectors. Both default to "let Aiden
decide" (Q3=B locked); if the operator supplies them, the values flow
into work_orders.requested_outputs jsonb (Q6=A) and Tier 1.5 PM honors
them at instantiation. POST /work_orders returns 201 with status=pending
immediately (Q1=B locked: no sync dispatch trigger). The auto-dispatch
worker (Phase 0.2) picks the WO up within one tick.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api

WO_TYPES = [
    "content_brief",
    "research_brief",
    "ad_hoc",
]
WO_PRIORITIES = ["low", "medium", "high", "critical"]

LET_AIDEN_DECIDE = "(let Aiden decide)"


def _load_template_profiles(api) -> list[dict]:
    """Fetch active template_profiles for the active tenant.

    Returns [] on any error (the form falls back to the Aiden-decides
    default and surfaces a hint, never blocks submission)."""
    try:
        return api.list_template_profiles(status="active")
    except APIError:
        return []


def main() -> None:
    st.markdown("## ＋ Submit Order")
    st.caption("Create a new Work Order for the active tenant.")

    api = page_requires_api()
    if api is None:
        return

    # Preflight the gate so we can surface a friendly message rather
    # than waiting for a 403 after form submission.
    try:
        decision = api.check_permission("work_order:create")
    except APIError as err:
        st.error(f"❌ perm check failed: {err.detail}")
        return

    if not decision.allowed:
        st.warning(
            f"Your role (`{decision.role or 'none'}`) does not hold "
            f"`work_order:create`. Switch to an operator/admin/owner in "
            f"the sidebar dev-auth picker."
        )
        return

    profiles = _load_template_profiles(api)
    output_kinds_available: list[str] = sorted({p["output_kind"] for p in profiles})

    # FF.AI Hotfix (2026-05-18) — render the last-created WO banner
    # ABOVE the form so it persists across reruns (st.form with
    # clear_on_submit=True wipes everything inside the form context,
    # which would blink the success message away as soon as the
    # operator touched anything else on the page).
    last_wo = st.session_state.get("_submit_order_last_wo")
    if last_wo:
        cols = st.columns([10, 1])
        with cols[0]:
            st.success(
                f"✅ Work Order created: `{last_wo['id']}` "
                f"(status: `{last_wo['status']}`)"
            )
            if last_wo.get("requested_outputs_summary"):
                st.caption(last_wo["requested_outputs_summary"])
            st.caption(
                "The auto-dispatch worker will pick this up within one tick "
                "(Phase 0.2). Open **Work Orders** to watch it advance."
            )
        with cols[1]:
            if st.button("Dismiss", key="dismiss-last-wo"):
                st.session_state.pop("_submit_order_last_wo", None)
                st.rerun()

    with st.form("submit-order", clear_on_submit=True):
        title = st.text_input(
            "Title *",
            placeholder="Draft RMIS one-pager for April brief",
        )
        description = st.text_area(
            "Description",
            placeholder="What should this work order produce? Who is the audience?",
        )
        col1, col2 = st.columns(2)
        with col1:
            wo_type = st.selectbox("Type", options=WO_TYPES, index=0)
        with col2:
            priority = st.selectbox("Priority", options=WO_PRIORITIES, index=1)

        st.markdown("##### Output (optional)")
        st.caption(
            "Pick a specific template (recommended for Gamma + 3rd-party "
            "renders), filter by output kind, or leave both on "
            f"\"{LET_AIDEN_DECIDE}\" to let Aiden infer from the brief."
        )

        def _label(p: dict) -> str:
            # e.g. "klear_pptx_primary — pptx via gamma"
            return f"{p['profile_key']} — {p['output_kind']} via {p['engine']}"

        col3, col4 = st.columns(2)
        with col3:
            kind_choice = st.selectbox(
                "Output kind",
                options=[LET_AIDEN_DECIDE] + output_kinds_available,
                index=0,
                help=(
                    "Optional filter that narrows the Template list. "
                    "Leave on (let Aiden decide) to see all templates."
                ),
            )
        # Templates are always pickable. The Output kind selector above
        # is a filter, not a gate — when set, it narrows this list;
        # when "(let Aiden decide)", we show every active template.
        if kind_choice == LET_AIDEN_DECIDE:
            profiles_for_kind = list(profiles)
        else:
            profiles_for_kind = [
                p for p in profiles if p["output_kind"] == kind_choice
            ]
        with col4:
            template_options = [LET_AIDEN_DECIDE] + [
                _label(p) for p in profiles_for_kind
            ]
            template_choice = st.selectbox(
                "Template",
                options=template_options,
                index=0,
                disabled=(len(profiles) == 0),
                help=(
                    f"Pick any active template directly — including Gamma "
                    f"and 3rd-party. {len(profiles)} active for this tenant."
                ),
            )

        correlation_id = st.text_input(
            "Correlation ID",
            placeholder="e.g. wo-klear-rmis-apr-001",
            help="Optional — groups related work for audit lineage.",
        )

        submitted = st.form_submit_button("Submit Order", type="primary")
        if submitted:
            if not title.strip():
                st.error("Title is required.")
                return

            output_kind: Optional[str] = (
                None if kind_choice == LET_AIDEN_DECIDE else kind_choice
            )
            template_profile_id: Optional[str] = None
            if template_choice != LET_AIDEN_DECIDE:
                # Match the chosen "{profile_key} — {kind} via {engine}"
                # label back to a row in `profiles_for_kind`.
                for p in profiles_for_kind:
                    if template_choice == _label(p):
                        template_profile_id = p["id"]
                        # If the operator picked a template without
                        # filtering by kind, derive output_kind from
                        # the chosen template — server will accept either
                        # the explicit pair or the implicit single field,
                        # and this keeps the audit row semantically full.
                        if output_kind is None:
                            output_kind = p["output_kind"]
                        break

            try:
                resp = api.create_work_order(
                    title=title.strip(),
                    description=description.strip() or None,
                    wo_type=wo_type,
                    priority=priority,
                    correlation_id=correlation_id.strip() or None,
                    output_kind=output_kind,
                    template_profile_id=template_profile_id,
                )
            except APIError as err:
                # API error — keep field values so the operator can
                # fix-and-retry without retyping. st.form's
                # clear_on_submit=True will clear the visible inputs,
                # but the operator still sees the error inline.
                st.error(f"❌ {err.status_code} — {err.detail}")
                return

            # Success — stash the result in session_state so the banner
            # renders ABOVE the (now-cleared) form on the next render
            # and persists across subsequent reruns until the operator
            # dismisses it or submits another WO.
            requested_outputs_summary: Optional[str] = None
            if output_kind is not None or template_profile_id is not None:
                requested_outputs_summary = (
                    f"Requested outputs recorded: "
                    f"`output_kind={output_kind or '—'}` / "
                    f"`template_profile_id={template_profile_id or '—'}`"
                )
            st.session_state["_submit_order_last_wo"] = {
                "id": resp.get("id", "—"),
                "status": resp.get("status", "—"),
                "requested_outputs_summary": requested_outputs_summary,
            }
            st.rerun()


main()
