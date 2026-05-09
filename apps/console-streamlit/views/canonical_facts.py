"""Loop Kappa — Memory V1.5 Canonical Facts CRUD operator surface.

Knowledge Base "Facts & Corrections" tab. Operators author tenant
canonical facts that hard-prepend to every Tier-1 chat turn.

Hybrid switch banner (D-K2):
  - "Table active" when canonical_facts has rows for this tenant.
  - "Folder fallback active" when the table is empty and the
    `Canonical Facts/` workspace folder is the source.

Severity vocabulary (D-K3): critical / high / medium / low. Severity
edits require `canonical_facts:set_severity` (owner / admin only) —
operators see the field disabled.

Audit emissions: `canonical_facts.created` / `.updated` / `.deleted`.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


_SEVERITY_OPTIONS = ["critical", "high", "medium", "low"]
_SEVERITY_BADGE = {
    "critical": ":red-background[**critical**]",
    "high":     ":orange-background[**high**]",
    "medium":   ":blue-background[**medium**]",
    "low":      ":gray-background[**low**]",
}


def _has_set_severity_permission() -> bool:
    """Best-effort role check — owners + admins only.

    The server enforces; this is a UI hint to disable the severity
    selector for operators. role is set on the dev-auth picker / JWT
    flow at sign-in.
    """
    role = (st.session_state.get("iwo3_current_user_role") or "").lower()
    return role in {"owner", "admin"}


def _can_create() -> bool:
    role = (st.session_state.get("iwo3_current_user_role") or "").lower()
    return role in {"owner", "admin", "operator"}


def _can_delete() -> bool:
    role = (st.session_state.get("iwo3_current_user_role") or "").lower()
    return role in {"owner", "admin"}


def _render_create_form(api) -> None:
    st.markdown("### Author a new canonical fact")
    with st.form("canonical_facts_create_form", clear_on_submit=True):
        body = st.text_area(
            "Body",
            placeholder=(
                "Write the authoritative fact here. Operators see "
                "this hard-prepended to every chat turn."
            ),
            max_chars=20_000,
            height=160,
        )
        sev_disabled = not _has_set_severity_permission()
        severity = st.selectbox(
            "Severity",
            options=_SEVERITY_OPTIONS,
            index=2,  # medium
            disabled=sev_disabled,
            help=(
                "Severity ordering: critical → high → medium → low. "
                "Edit requires owner/admin (canonical_facts:set_severity)."
                if sev_disabled
                else None
            ),
        )
        submitted = st.form_submit_button(
            "Save fact", type="primary", disabled=not _can_create()
        )
    if submitted:
        if not body.strip():
            st.error("Body is required.")
            return
        try:
            api.create_canonical_fact(
                body=body.strip(),
                severity=severity if not sev_disabled else "medium",
            )
            st.success("Fact saved. Memory bundle will see it on the next chat turn.")
            st.rerun()
        except APIError as exc:
            st.error(f"Save failed: {exc.detail}")


def _render_fact_row(api, fact: dict, *, can_edit: bool, can_delete_row: bool) -> None:
    fact_id = fact["id"]
    severity = fact.get("severity", "medium")
    badge = _SEVERITY_BADGE.get(severity, severity)
    version = fact.get("version", 1)
    is_active = fact.get("is_active", True)

    with st.container(border=True):
        cols = st.columns([0.7, 0.3])
        with cols[0]:
            st.markdown(f"{badge} &nbsp; v{version}{'' if is_active else ' &nbsp; _(inactive)_'}")
        with cols[1]:
            st.caption(f"`{fact_id[:8]}` · authored {fact.get('created_at', '')[:10]}")
        st.write(fact.get("body", ""))

        with st.expander("Edit", expanded=False):
            with st.form(f"edit_form_{fact_id}", clear_on_submit=False):
                new_body = st.text_area(
                    "Body",
                    value=fact.get("body", ""),
                    max_chars=20_000,
                    height=120,
                )
                sev_disabled = not _has_set_severity_permission()
                new_severity = st.selectbox(
                    "Severity",
                    options=_SEVERITY_OPTIONS,
                    index=_SEVERITY_OPTIONS.index(severity) if severity in _SEVERITY_OPTIONS else 2,
                    disabled=sev_disabled,
                )
                new_is_active = st.checkbox("Active", value=is_active)

                btn_cols = st.columns(2)
                with btn_cols[0]:
                    save = st.form_submit_button(
                        "Save changes",
                        type="primary",
                        disabled=not can_edit,
                    )
                with btn_cols[1]:
                    delete = st.form_submit_button(
                        "Delete (soft)",
                        type="secondary",
                        disabled=not can_delete_row or not is_active,
                    )

            if save:
                try:
                    payload: dict = {}
                    if new_body != fact.get("body"):
                        payload["body"] = new_body
                    if new_is_active != is_active:
                        payload["is_active"] = new_is_active
                    if not sev_disabled and new_severity != severity:
                        payload["severity"] = new_severity
                    if not payload:
                        st.info("No changes.")
                    else:
                        api.update_canonical_fact(fact_id, **payload)
                        st.success("Updated.")
                        st.rerun()
                except APIError as exc:
                    st.error(f"Update failed: {exc.detail}")
            if delete:
                try:
                    api.delete_canonical_fact(fact_id)
                    st.success("Deleted (soft).")
                    st.rerun()
                except APIError as exc:
                    st.error(f"Delete failed: {exc.detail}")


def main() -> None:
    page_requires_api()
    api = st.session_state["iwo3_api"]
    tenant_label = st.session_state.get("iwo3_current_tenant_label", "this tenant")

    st.markdown("# Canonical Facts")
    st.caption(
        "Authoritative facts that hard-prepend to every chat turn for "
        f"**{tenant_label}**. The Memory V1 budget never drops these."
    )

    show_inactive = st.toggle("Include inactive (soft-deleted) rows", value=False)

    try:
        listed = api.list_canonical_facts(include_inactive=show_inactive)
    except APIError as exc:
        st.error(f"Could not load canonical facts: {exc.detail}")
        return

    rows = listed.get("rows", [])
    blob_revision = listed.get("blob_revision", 0)

    # D-K2 hybrid switch banner.
    if rows:
        st.info(
            f"**Table active** — {len(rows)} row(s) for this tenant. "
            f"Memory blob revision: `{blob_revision}`."
        )
    else:
        st.warning(
            "**Folder fallback active** — no rows in the canonical_facts "
            "table for this tenant. Memory V1 reads facts from the "
            "`Canonical Facts/` workspace folder when present. Author "
            "your first table-driven fact below to switch to the "
            "structured surface."
        )

    if _can_create():
        _render_create_form(api)
    else:
        st.caption("_Read-only access — your role cannot author canonical facts._")

    if rows:
        st.markdown("### Existing facts")
        can_edit = (
            (st.session_state.get("iwo3_current_user_role") or "").lower()
            in {"owner", "admin", "operator"}
        )
        can_delete_row = _can_delete()
        for fact in rows:
            _render_fact_row(api, fact, can_edit=can_edit, can_delete_row=can_delete_row)


main()
