"""Workspace — IWO2 visual idiom matched to client/src/pages/workspace.tsx.

Architect lock 2026-04-26 §D2 (`IWO3_DESIGN_MEGALOOP_ARCHITECT_LOCK_v0.1.0`):
visual parity first, backend parity preserved, abstraction deferred. The
IWO2 React workspace is the direct visual reference; the IWO3 FastAPI
workspace contract (tree, content fetch, scratch, folder/file CRUD,
RBAC) is preserved exactly.

What changed (presentation only):
- Compact responsive card grid (2–6 cols) with small radii and no gradients
- Breadcrumb header with chevron-separated path and "New" popover on the right
- Per-card ⋮ overflow menu (Streamlit popover) for Rename / Move / Delete
- Preview pane stacks below the grid (Streamlit cannot split-pane; matches
  IWO2's right-side preview semantics on a single column)
- No 4-stat decorative strip, no marketing subtitle, no uppercase chrome
- Empty / loading / error copy reads operationally, not apologetically

What did NOT change (backend / RBAC):
- Every action still calls FastAPI: GET /workspace/tree, /workspace/folders/{id},
  /workspace/files/{id}/content; POST /workspace/folders, /workspace/folders/scratch,
  /workspace/files; PATCH /workspace/folders/{id}, /workspace/files/{id};
  DELETE /workspace/folders/{id}, /workspace/files/{id}
- workspace:write / workspace:delete still derived from check_permission and
  used cosmetically only — server enforces
- Drag-drop bulk-move panel preserved behind an expander (operational, not
  primary affordance)

Known parity gap: IWO2 has in-place file edit. IWO3 has no PUT for file
content; adding one is a backend change (architect lock §5 forbids without
explicit reauthorization). Preview-only in this commit.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


try:
    from streamlit_sortables import sort_items as _sort_items
    _SORTABLES_AVAILABLE = True
except Exception:  # noqa: BLE001 — optional dep
    _sort_items = None
    _SORTABLES_AVAILABLE = False


_SS_FOCUS_FOLDER = "workspace_focus_folder_id"
_SS_PREVIEW_FILE = "workspace_preview_file_id"


_FOLDER_HINTS = {
    "00_Planning": "Strategic plans, roadmaps, and objectives",
    "01_Directive-SOP": "Standard operating procedures and directives",
    "02_Execution": "Execution logs, outputs, and deliverables",
    "03_Orchestration": "Workflow configurations and orchestration files",
    "04_Resources": "Shared resources, templates, and reference materials",
    "05_Artifacts": "Final work products and completed artifacts",
    "06_Tests": "Test plans, results, and validation reports",
    "Outputs": "Auto-routed work order outputs and deliverables",
    "Scratch (you)": "Private draft area visible only to you",
}


def _inject_css() -> None:
    """IWO2-shaped Streamlit CSS. Small radii, hover-elevate, 150ms motion,
    no gradients. Color palette aligns with the existing
    ``apps/console-streamlit/.streamlit/config.toml`` primary
    (``#1E5F91``) so this page does not invent a third blue."""
    st.markdown(
        """
        <style>
        :root {
          --ws-border: #e5e7eb;
          --ws-border-strong: #cbd5e1;
          --ws-text: #111827;
          --ws-muted: #6b7280;
          --ws-muted-soft: #94a3b8;
          --ws-primary: #1E5F91;
          --ws-primary-soft: rgba(30, 95, 145, 0.08);
          --ws-surface: #ffffff;
          --ws-surface-alt: #f8fafc;
        }

        .ws-page-title {
          font-size: 1.25rem;
          font-weight: 600;
          color: var(--ws-text);
          margin: 0 0 0.6rem 0;
        }

        .ws-crumb-row {
          display: flex; align-items: center; gap: 0.25rem;
          flex-wrap: wrap;
          font-size: 0.86rem;
          color: var(--ws-muted);
          margin-bottom: 0.65rem;
        }
        .ws-crumb-sep {
          color: var(--ws-muted-soft);
          font-size: 0.78rem;
          padding: 0 0.1rem;
        }
        .ws-crumb-label {
          color: var(--ws-muted);
          font-size: 0.78rem;
        }

        .ws-divider {
          border: 0;
          border-top: 1px solid var(--ws-border);
          margin: 0.85rem 0 0.85rem 0;
        }

        .ws-folder-note {
          font-size: 0.82rem;
          color: var(--ws-muted);
          margin: 0 0 0.85rem 0;
        }

        /* Card chrome — applied to st.container(border=True) where
           Streamlit emits data-testid="stContainer" wrappers. We tighten
           radii + remove the default border colour and use a subtle one. */
        .ws-card-grid div[data-testid="stVerticalBlockBorderWrapper"] {
          border: 1px solid var(--ws-border) !important;
          border-radius: 6px !important;
          background: var(--ws-surface) !important;
          padding: 0.55rem 0.55rem 0.45rem 0.55rem !important;
          transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease !important;
          min-height: 158px;
        }
        .ws-card-grid div[data-testid="stVerticalBlockBorderWrapper"]:hover {
          border-color: var(--ws-primary) !important;
          box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06) !important;
        }

        .ws-card-icon {
          font-size: 1.85rem;
          line-height: 1;
          margin: 0.05rem 0 0.3rem 0;
          text-align: center;
        }
        .ws-card-icon-folder { color: var(--ws-primary); }
        .ws-card-name {
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--ws-text);
          text-align: center;
          line-height: 1.25;
          word-break: break-word;
          margin: 0;
        }
        .ws-card-meta {
          font-size: 0.68rem;
          color: var(--ws-muted);
          text-align: center;
          line-height: 1.3;
          margin: 0.15rem 0 0 0;
          min-height: 1.6em;
        }
        .ws-card-private {
          color: var(--ws-primary);
          font-weight: 500;
        }

        /* Per-card buttons row — small, side-by-side */
        .ws-card-grid div[data-testid="stButton"] > button {
          border-radius: 4px;
          font-size: 0.74rem;
          font-weight: 500;
          padding: 0.2rem 0.4rem;
          min-height: 1.7rem;
          border: 1px solid var(--ws-border);
          background: var(--ws-surface);
          color: var(--ws-text);
          transition: all 150ms ease;
        }
        .ws-card-grid div[data-testid="stButton"] > button:hover {
          border-color: var(--ws-primary);
          color: var(--ws-primary);
        }
        .ws-card-grid div[data-testid="stPopover"] > button {
          border-radius: 4px;
          font-size: 0.74rem;
          padding: 0.2rem 0.4rem;
          min-height: 1.7rem;
          border: 1px solid var(--ws-border);
          background: var(--ws-surface);
          color: var(--ws-muted);
          font-weight: 600;
        }

        /* Header New popover — solid primary so it reads as the main action */
        .ws-toolbar div[data-testid="stPopover"] > button {
          border-radius: 4px;
          background: var(--ws-primary);
          color: #ffffff;
          border: 1px solid var(--ws-primary);
          font-weight: 500;
          font-size: 0.82rem;
          padding: 0.3rem 0.7rem;
          min-height: 2rem;
        }
        .ws-toolbar div[data-testid="stButton"] > button {
          border-radius: 4px;
          font-size: 0.82rem;
          font-weight: 500;
          min-height: 2rem;
          padding: 0.3rem 0.7rem;
          border: 1px solid var(--ws-border);
          background: var(--ws-surface);
          color: var(--ws-text);
        }
        .ws-toolbar div[data-testid="stButton"] > button[kind="primary"] {
          background: var(--ws-primary);
          color: #ffffff;
          border-color: var(--ws-primary);
        }

        /* Empty state */
        .ws-empty {
          padding: 3.2rem 1rem;
          text-align: center;
          color: var(--ws-muted);
        }
        .ws-empty-icon { font-size: 2.6rem; margin-bottom: 0.7rem; opacity: 0.7; }
        .ws-empty-title { font-size: 1rem; font-weight: 600; color: var(--ws-text); margin-bottom: 0.4rem; }
        .ws-empty-body { font-size: 0.84rem; max-width: 32rem; margin: 0 auto; line-height: 1.5; }

        /* Preview pane */
        .ws-preview {
          border: 1px solid var(--ws-border);
          border-radius: 6px;
          background: var(--ws-surface);
          margin-top: 1rem;
        }
        .ws-preview-header {
          display: flex; align-items: center; justify-content: space-between;
          gap: 0.5rem;
          padding: 0.6rem 0.85rem;
          border-bottom: 1px solid var(--ws-border);
        }
        .ws-preview-title {
          font-size: 0.88rem;
          font-weight: 600;
          color: var(--ws-text);
          display: flex; align-items: center; gap: 0.45rem;
          min-width: 0;
        }
        .ws-preview-title-name {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 32rem;
        }
        .ws-preview-meta {
          padding: 0.6rem 0.85rem 0.55rem 0.85rem;
          border-bottom: 1px solid var(--ws-border);
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 0.45rem 1rem;
          font-size: 0.74rem;
        }
        .ws-meta-label { color: var(--ws-muted); }
        .ws-meta-value { color: var(--ws-text); }
        .ws-preview-body { padding: 0.6rem 0.85rem 0.6rem 0.85rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _ts(value: object) -> str:
    if not value:
        return "—"
    return str(value).replace("T", " ").replace("+00:00", " UTC")


def _humanise_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1_048_576:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1_048_576:.2f} MB"


def _folder_hint(folder: dict[str, Any]) -> str:
    if folder.get("is_root"):
        return "Tenant root for plans, artifacts, scratch work, and deliverables."
    if folder.get("owner_user_id"):
        return _FOLDER_HINTS.get(folder.get("name") or "", "Private draft area visible only to you")
    return _FOLDER_HINTS.get(folder.get("name") or "", "Folder in the tenant workspace")


def _folder_icon(folder: dict[str, Any]) -> str:
    if folder.get("is_root"):
        return "🗂️"
    if folder.get("owner_user_id"):
        return "🗒️"
    return "📁"


def _file_emoji(file_row: dict[str, Any]) -> str:
    mime = file_row.get("mime_type") or ""
    filename = (file_row.get("filename") or "").lower()
    source_type = file_row.get("source_type") or ""
    if filename.startswith("preview:") or source_type == "external_preview":
        return "🌐"
    if mime.startswith("image/"):
        return "🖼️"
    if "pdf" in mime:
        return "📕"
    if "presentation" in mime or mime.endswith("pptx"):
        return "📊"
    if "markdown" in mime or filename.endswith(".md"):
        return "📝"
    if "json" in mime or filename.endswith(".json"):
        return "🔧"
    if "csv" in mime or filename.endswith(".csv"):
        return "📈"
    return "📄"


def _children_by_parent(folders: list[dict[str, Any]]) -> dict[str | None, list[dict[str, Any]]]:
    out: dict[str | None, list[dict[str, Any]]] = {}
    for folder in folders:
        out.setdefault(folder.get("parent_folder_id"), []).append(folder)
    return out


def _files_by_folder(files: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for file_row in files:
        folder_id = file_row.get("workspace_folder_id")
        if folder_id:
            out.setdefault(folder_id, []).append(file_row)
    return out


def _set_focus(folder_id: str) -> None:
    st.session_state[_SS_FOCUS_FOLDER] = folder_id


def _set_preview(file_id: str) -> None:
    st.session_state[_SS_PREVIEW_FILE] = file_id


def _clear_preview() -> None:
    st.session_state.pop(_SS_PREVIEW_FILE, None)


def _lineage(folder: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    chain = [folder]
    current = folder
    while current.get("parent_folder_id"):
        current = by_id[current["parent_folder_id"]]
        chain.append(current)
    chain.reverse()
    return chain


def _move_target_options(
    folders: list[dict[str, Any]],
    *,
    exclude_self: Optional[str] = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    excluded: set[str] = set()
    if exclude_self:
        children = _children_by_parent(folders)
        stack = [exclude_self]
        while stack:
            current = stack.pop()
            excluded.add(current)
            for child in children.get(current, []):
                stack.append(child["id"])
    for folder in folders:
        if folder["id"] in excluded:
            continue
        out.append(folder)
    return out


def _folder_target_label(folder: dict[str, Any]) -> str:
    return "Workspace" if folder.get("is_root") else folder["name"]


# ── Header (breadcrumb + actions) ─────────────────────────────────────


def _render_breadcrumb(lineage: list[dict[str, Any]]) -> None:
    """Render the lineage as a chevron-separated row of buttons. Matches
    IWO2 ``breadcrumbs.map`` rendering with a Home icon on the first item."""
    cols = st.columns([1] * len(lineage) + [4])
    for idx, (col, folder) in enumerate(zip(cols, lineage)):
        with col:
            label = ("🏠 Workspace" if idx == 0 else folder["name"])
            if st.button(
                label,
                key=f"workspace-crumb-{folder['id']}",
                use_container_width=True,
                disabled=(idx == len(lineage) - 1),
            ):
                _set_focus(folder["id"])
                _clear_preview()
                st.rerun()


def _render_new_popover(api, parent_id: str, scratch: Optional[dict[str, Any]], can_write: bool) -> None:  # noqa: ANN001
    popover = getattr(st, "popover", None)
    if popover is None:
        # Pre-1.31 Streamlit fallback: expander
        with st.expander("➕ New", expanded=False):
            _render_new_menu_body(api, parent_id, scratch, can_write)
        return
    with popover("➕ New", use_container_width=True, disabled=not can_write):
        _render_new_menu_body(api, parent_id, scratch, can_write)


def _render_new_menu_body(api, parent_id: str, scratch: Optional[dict[str, Any]], can_write: bool) -> None:  # noqa: ANN001
    if not can_write:
        st.caption("Read-only: `workspace:write` required.")
        return
    tab_folder, tab_file, tab_scratch = st.tabs(["Folder", "File", "Scratch"])
    with tab_folder:
        _render_new_folder_form(api, parent_id)
    with tab_file:
        _render_new_file_form(api, parent_id)
    with tab_scratch:
        _render_scratch_action(api, scratch)


def _render_new_folder_form(api, parent_id: str) -> None:  # noqa: ANN001
    with st.form(f"workspace-newfolder-{parent_id}", clear_on_submit=True):
        name = st.text_input("Folder name", placeholder="e.g. Drafts")
        submit = st.form_submit_button("Create folder", type="primary")
        if submit and name.strip():
            try:
                api._request(
                    "POST",
                    "/workspace/folders",
                    json={"parent_folder_id": parent_id, "name": name.strip()},
                )
                st.success(f"Folder `{name}` created.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.status_code} — {err.detail}")


def _render_new_file_form(api, parent_id: str) -> None:  # noqa: ANN001
    with st.form(f"workspace-newfile-{parent_id}", clear_on_submit=True):
        col1, col2 = st.columns([2, 1])
        with col1:
            filename = st.text_input("File name", placeholder="notes.md")
        with col2:
            mime = st.selectbox(
                "Type",
                ["text/markdown", "text/plain", "application/json", "text/csv"],
                index=0,
            )
        text = st.text_area("Content", height=120, placeholder="(optional)")
        upload = st.file_uploader(
            "…or upload a file (overrides text content)",
            type=None,
            accept_multiple_files=False,
        )
        submit = st.form_submit_button("Create file", type="primary")
        if submit and filename.strip():
            payload: dict[str, Any] = {
                "workspace_folder_id": parent_id,
                "filename": filename.strip(),
                "mime_type": mime,
            }
            if upload is not None:
                payload["mime_type"] = upload.type or mime
                payload["content_b64"] = base64.b64encode(upload.getvalue()).decode("ascii")
            else:
                payload["content_text"] = text
            try:
                api._request("POST", "/workspace/files", json=payload)
                st.success(f"File `{filename}` created.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.status_code} — {err.detail}")


def _render_scratch_action(api, scratch: Optional[dict[str, Any]]) -> None:  # noqa: ANN001
    if scratch is not None:
        st.caption(
            "Your private scratch folder is visible only to you and lives at the workspace root."
        )
        if st.button("🗒️ Open my scratch", use_container_width=True, type="primary", key="ws-scratch-open"):
            _set_focus(scratch["id"])
            _clear_preview()
            st.rerun()
        return
    st.caption("Per-operator scratch is private — only you see it.")
    if st.button("🗒️ Create my scratch folder", use_container_width=True, type="primary", key="ws-scratch-create"):
        try:
            resp = api.create_or_get_scratch_folder()
            _set_focus(resp["folder"]["id"])
            st.success("Scratch folder ready.")
            st.rerun()
        except APIError as err:
            st.error(f"{err.status_code} — {err.detail}")


def _render_header(
    api,  # noqa: ANN001
    *,
    lineage: list[dict[str, Any]],
    selected: dict[str, Any],
    root_id: str,
    scratch: Optional[dict[str, Any]],
    can_write: bool,
) -> None:
    st.markdown('<div class="ws-toolbar">', unsafe_allow_html=True)
    cols = st.columns([6, 1, 1])
    with cols[0]:
        _render_breadcrumb(lineage)
    with cols[1]:
        parent_id = selected.get("parent_folder_id")
        if st.button(
            "← Up",
            use_container_width=True,
            disabled=parent_id is None,
            key="ws-toolbar-up",
        ):
            _set_focus(parent_id or root_id)
            _clear_preview()
            st.rerun()
    with cols[2]:
        _render_new_popover(api, selected["id"], scratch, can_write)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Card grid ─────────────────────────────────────────────────────────


def _render_folder_card(
    api,  # noqa: ANN001
    folder: dict[str, Any],
    *,
    children_map: dict[str | None, list[dict[str, Any]]],
    files_map: dict[str, list[dict[str, Any]]],
    all_folders: list[dict[str, Any]],
    can_write: bool,
    can_delete: bool,
) -> None:
    sub_count = len(children_map.get(folder["id"], []))
    file_count = len(files_map.get(folder["id"], []))
    chips: list[str] = []
    if sub_count:
        chips.append(f"{sub_count} folder{'s' if sub_count != 1 else ''}")
    if file_count:
        chips.append(f"{file_count} file{'s' if file_count != 1 else ''}")
    if folder.get("owner_user_id"):
        chips.append('<span class="ws-card-private">private</span>')
    meta = " · ".join(chips) if chips else "Empty"

    with st.container(border=True):
        st.markdown(
            f"""
            <div class="ws-card-icon ws-card-icon-folder">{_folder_icon(folder)}</div>
            <div class="ws-card-name">{folder['name'] if not folder.get('is_root') else 'Workspace'}</div>
            <div class="ws-card-meta">{meta}</div>
            """,
            unsafe_allow_html=True,
        )
        action_cols = st.columns([3, 1])
        with action_cols[0]:
            if st.button("Open", key=f"ws-folder-open-{folder['id']}", use_container_width=True):
                _set_focus(folder["id"])
                _clear_preview()
                st.rerun()
        with action_cols[1]:
            _render_folder_overflow(api, folder, all_folders, can_write, can_delete)


def _render_folder_overflow(
    api,  # noqa: ANN001
    folder: dict[str, Any],
    all_folders: list[dict[str, Any]],
    can_write: bool,
    can_delete: bool,
) -> None:
    popover = getattr(st, "popover", None)
    if folder.get("is_root"):
        # No actions on the tenant root; render a disabled placeholder so
        # the grid layout stays consistent.
        st.button("⋮", key=f"ws-folder-menu-root-{folder['id']}", disabled=True, use_container_width=True)
        return
    if popover is None:
        st.button("⋮", key=f"ws-folder-menu-noop-{folder['id']}", disabled=True, use_container_width=True, help="Streamlit popover not available")
        return
    with popover("⋮", use_container_width=True):
        st.markdown(f"**{folder['name']}**")
        new_name = st.text_input(
            "Rename",
            value=folder["name"],
            key=f"ws-folder-rename-{folder['id']}",
        )
        if st.button(
            "Save name",
            key=f"ws-folder-rename-btn-{folder['id']}",
            disabled=not can_write or new_name.strip() == folder["name"],
            use_container_width=True,
        ):
            try:
                api._request("PATCH", f"/workspace/folders/{folder['id']}", json={"name": new_name.strip()})
                st.success("Folder renamed.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.detail}")

        targets = _move_target_options(all_folders, exclude_self=folder["id"])
        target_id = st.selectbox(
            "Move under",
            [t["id"] for t in targets],
            format_func=lambda tid: next(
                (_folder_target_label(t) for t in targets if t["id"] == tid),
                tid,
            ),
            key=f"ws-folder-move-{folder['id']}",
        )
        if st.button(
            "Move",
            key=f"ws-folder-move-btn-{folder['id']}",
            disabled=not can_write,
            use_container_width=True,
        ):
            try:
                api._request("PATCH", f"/workspace/folders/{folder['id']}", json={"parent_folder_id": target_id})
                st.success("Folder moved.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.detail}")

        st.divider()
        if st.button(
            f"🗑️ Delete `{folder['name']}`",
            key=f"ws-folder-delete-{folder['id']}",
            disabled=not can_delete,
            help=None if can_delete else "Requires workspace:delete (admin/owner)",
            use_container_width=True,
        ):
            try:
                api._request("DELETE", f"/workspace/folders/{folder['id']}")
                st.success("Folder deleted.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.detail}")


def _render_file_card(
    api,  # noqa: ANN001
    file_row: dict[str, Any],
    *,
    all_folders: list[dict[str, Any]],
    can_write: bool,
    can_delete: bool,
) -> None:
    name = file_row.get("filename") or file_row["id"][:8]
    mime_label = file_row.get("mime_type") or "—"
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="ws-card-icon">{_file_emoji(file_row)}</div>
            <div class="ws-card-name">{name}</div>
            <div class="ws-card-meta">{mime_label}</div>
            """,
            unsafe_allow_html=True,
        )
        action_cols = st.columns([3, 1])
        with action_cols[0]:
            if st.button("Preview", key=f"ws-file-preview-{file_row['id']}", use_container_width=True):
                _set_preview(file_row["id"])
                st.rerun()
        with action_cols[1]:
            _render_file_overflow(api, file_row, all_folders, can_write, can_delete)


def _render_file_overflow(
    api,  # noqa: ANN001
    file_row: dict[str, Any],
    all_folders: list[dict[str, Any]],
    can_write: bool,
    can_delete: bool,
) -> None:
    popover = getattr(st, "popover", None)
    if popover is None:
        st.button("⋮", key=f"ws-file-menu-noop-{file_row['id']}", disabled=True, use_container_width=True, help="Streamlit popover not available")
        return
    name = file_row.get("filename") or file_row["id"][:8]
    with popover("⋮", use_container_width=True):
        st.markdown(f"**{name}**")
        new_name = st.text_input(
            "Rename",
            value=name,
            key=f"ws-file-rename-{file_row['id']}",
        )
        if st.button(
            "Save name",
            key=f"ws-file-rename-btn-{file_row['id']}",
            disabled=not can_write or new_name.strip() == name,
            use_container_width=True,
        ):
            try:
                api._request("PATCH", f"/workspace/files/{file_row['id']}", json={"filename": new_name.strip()})
                st.success("File renamed.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.detail}")

        target_id = st.selectbox(
            "Move to",
            [folder["id"] for folder in all_folders],
            format_func=lambda tid: next(
                (_folder_target_label(folder) for folder in all_folders if folder["id"] == tid),
                tid,
            ),
            key=f"ws-file-move-{file_row['id']}",
        )
        if st.button(
            "Move",
            key=f"ws-file-move-btn-{file_row['id']}",
            disabled=not can_write,
            use_container_width=True,
        ):
            try:
                api._request("PATCH", f"/workspace/files/{file_row['id']}", json={"workspace_folder_id": target_id})
                st.success("File moved.")
                st.rerun()
            except APIError as err:
                st.error(f"{err.detail}")

        st.divider()
        if st.button(
            "🗑️ Remove from workspace",
            key=f"ws-file-delete-{file_row['id']}",
            disabled=not can_delete,
            help=None if can_delete else "Requires workspace:delete (admin/owner)",
            use_container_width=True,
        ):
            try:
                api._request("DELETE", f"/workspace/files/{file_row['id']}")
                st.success("File removed.")
                _clear_preview()
                st.rerun()
            except APIError as err:
                st.error(f"{err.detail}")


def _render_grid(
    api,  # noqa: ANN001
    *,
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
    all_folders: list[dict[str, Any]],
    children_map: dict[str | None, list[dict[str, Any]]],
    files_map: dict[str, list[dict[str, Any]]],
    can_write: bool,
    can_delete: bool,
) -> None:
    items: list[tuple[str, dict[str, Any]]] = []
    items.extend(("folder", f) for f in sorted(folders, key=lambda x: x["name"].lower()))
    items.extend(("file", f) for f in sorted(files, key=lambda x: (x.get("filename") or "").lower()))

    if not items:
        st.markdown(
            """
            <div class="ws-empty">
              <div class="ws-empty-icon">📁</div>
              <div class="ws-empty-title">Empty folder</div>
              <div class="ws-empty-body">Create a folder or file with the New menu, or move outputs here from <code>Outputs/</code>.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown('<div class="ws-card-grid">', unsafe_allow_html=True)
    cols_per_row = 5 if len(items) >= 5 else max(1, len(items))
    for start in range(0, len(items), cols_per_row):
        cols = st.columns(cols_per_row, gap="small")
        for col, (kind, payload) in zip(cols, items[start:start + cols_per_row]):
            with col:
                if kind == "folder":
                    _render_folder_card(
                        api,
                        payload,
                        children_map=children_map,
                        files_map=files_map,
                        all_folders=all_folders,
                        can_write=can_write,
                        can_delete=can_delete,
                    )
                else:
                    _render_file_card(
                        api,
                        payload,
                        all_folders=all_folders,
                        can_write=can_write,
                        can_delete=can_delete,
                    )
    st.markdown("</div>", unsafe_allow_html=True)


# ── Preview pane ──────────────────────────────────────────────────────


def _render_preview(api, file_row: dict[str, Any]) -> None:  # noqa: ANN001
    try:
        content = api.get_workspace_file_content(file_row["id"])
    except APIError as err:
        st.error(f"{err.status_code} — {err.detail}")
        return

    name = file_row.get("filename") or file_row["id"][:8]
    mime = content.get("mime_type") or "—"
    size = _humanise_bytes(int(content.get("size_bytes") or 0))
    encoding = content.get("encoding") or "—"
    source = file_row.get("source_type") or "—"

    st.markdown('<div class="ws-preview">', unsafe_allow_html=True)
    header_cols = st.columns([6, 1])
    with header_cols[0]:
        st.markdown(
            f"""
            <div class="ws-preview-header">
              <div class="ws-preview-title">
                <span>{_file_emoji(file_row)}</span>
                <span class="ws-preview-title-name">{name}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with header_cols[1]:
        if st.button("× Close", key=f"ws-preview-close-{file_row['id']}", use_container_width=True):
            _clear_preview()
            st.rerun()

    st.markdown(
        f"""
        <div class="ws-preview-meta">
          <div><span class="ws-meta-label">Type</span><br><span class="ws-meta-value">{mime}</span></div>
          <div><span class="ws-meta-label">Size</span><br><span class="ws-meta-value">{size}</span></div>
          <div><span class="ws-meta-label">Encoding</span><br><span class="ws-meta-value">{encoding}</span></div>
          <div><span class="ws-meta-label">Source</span><br><span class="ws-meta-value">{source}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="ws-preview-body">', unsafe_allow_html=True)
    payload = content.get("content")
    if encoding == "utf-8":
        if "json" in mime:
            st.code(payload or "", language="json")
        elif "markdown" in mime or (file_row.get("filename") or "").lower().endswith(".md"):
            st.code(payload or "", language="markdown")
        elif mime == "text/csv":
            st.code(payload or "", language="text")
        else:
            st.code(payload or "", language="text")
    elif encoding == "base64" and payload and (mime or "").startswith("image/"):
        try:
            st.image(base64.b64decode(payload), caption=name)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Image decode failed: {exc}")
    elif encoding == "base64":
        st.info("Binary content stored inline. Direct download is not yet wired in this loop.")
    elif encoding == "ref":
        storage_ref = content.get("storage_ref") or file_row.get("storage_ref") or ""
        if storage_ref.startswith("output_package://"):
            st.info(
                "This file points to an Output Package-backed deliverable. "
                "Open the Output Packages page for the canonical package and handoff state."
            )
            st.code(storage_ref)
        else:
            st.info("File is stored by reference, not inline.")
            st.code(storage_ref or "(no storage ref)")
    if content.get("truncated"):
        st.warning("Preview truncated to keep the page responsive.")
    st.markdown("</div></div>", unsafe_allow_html=True)


# ── Bulk move (drag-drop fallback panel — IWO3-only operator affordance) ──


def _render_bulk_move(api, folder: dict[str, Any], files: list[dict[str, Any]], sibling_folders: list[dict[str, Any]]) -> None:  # noqa: ANN001
    """Drag rows between folder buckets to move files. This is an IWO3
    operator affordance, not an IWO2 idiom — IWO2 supports HTML5 drag on
    each card. Streamlit cannot reproduce that on st.container, so this
    panel is the working alternative. Demoted behind an expander so it is
    not the primary affordance.
    """
    if not _SORTABLES_AVAILABLE or _sort_items is None or not sibling_folders or not files:
        return
    with st.expander("Bulk move via drag-drop", expanded=False):
        st.caption(
            "Drag a file row into a sibling-folder bucket below to move it. "
            "Card-level drag-drop is not yet supported in Streamlit — use the ⋮ menu on each card for single-card moves."
        )
        items: list[dict[str, Any]] = [
            {
                "header": folder["name"],
                "items": [
                    f"{_file_emoji(file_row)} {file_row.get('filename') or file_row['id'][:8]}::{file_row['id']}"
                    for file_row in files
                ],
            }
        ]
        sibling_id_by_label = {sibling["name"]: sibling["id"] for sibling in sibling_folders}
        for sibling in sibling_folders:
            items.append({"header": sibling["name"], "items": []})

        sorted_state = _sort_items(
            items,
            multi_containers=True,
            direction="vertical",
            key=f"workspace-dragdrop-{folder['id']}",
        )
        if not sorted_state:
            return
        for bucket in sorted_state:
            target_id = sibling_id_by_label.get(bucket.get("header"))
            if target_id is None:
                continue
            for label in bucket.get("items", []):
                if "::" not in label:
                    continue
                file_id = label.split("::", 1)[1]
                try:
                    api._request(
                        "PATCH",
                        f"/workspace/files/{file_id}",
                        json={"workspace_folder_id": target_id},
                    )
                except APIError as err:
                    st.error(f"Move failed for `{file_id[:8]}…`: {err.detail}")


# ── Page ──────────────────────────────────────────────────────────────


def main() -> None:
    _inject_css()
    st.markdown('<div class="ws-page-title">Workspace</div>', unsafe_allow_html=True)

    api = page_requires_api()
    if api is None:
        return

    try:
        tree = api.get_workspace_tree()
        can_write = api.check_permission("workspace:write").allowed
        can_delete = api.check_permission("workspace:delete").allowed
    except APIError as err:
        st.error(f"{err.status_code} — {err.detail}")
        return

    folders: list[dict[str, Any]] = tree["folders"]
    files: list[dict[str, Any]] = tree["files"]
    if not folders:
        st.info("No workspace folders for this tenant. Run the seed loader so the tenant has a root and `Outputs/`.")
        return

    by_id = {folder["id"]: folder for folder in folders}
    children_map = _children_by_parent(folders)
    files_map = _files_by_folder(files)
    root = next(folder for folder in folders if folder.get("is_root"))
    selected_id = st.session_state.get(_SS_FOCUS_FOLDER, root["id"])
    if selected_id not in by_id:
        selected_id = root["id"]
        st.session_state[_SS_FOCUS_FOLDER] = selected_id
    selected = by_id[selected_id]
    lineage = _lineage(selected, by_id)

    scratch = next(
        (
            folder
            for folder in folders
            if folder.get("owner_user_id") and folder.get("parent_folder_id") == root["id"]
        ),
        None,
    )

    _render_header(
        api,
        lineage=lineage,
        selected=selected,
        root_id=root["id"],
        scratch=scratch,
        can_write=can_write,
    )

    st.markdown(f'<div class="ws-folder-note">{_folder_hint(selected)}</div>', unsafe_allow_html=True)

    child_folders = sorted(children_map.get(selected_id, []), key=lambda x: x["name"].lower())
    own_files = sorted(files_map.get(selected_id, []), key=lambda x: (x.get("filename") or "").lower())

    _render_grid(
        api,
        folders=child_folders,
        files=own_files,
        all_folders=folders,
        children_map=children_map,
        files_map=files_map,
        can_write=can_write,
        can_delete=can_delete,
    )

    preview_id = st.session_state.get(_SS_PREVIEW_FILE)
    if preview_id:
        file_by_id = {file_row["id"]: file_row for file_row in files}
        file_row = file_by_id.get(preview_id)
        if file_row is not None:
            _render_preview(api, file_row)

    sibling_folders = [folder for folder in child_folders if folder["id"] != selected_id]
    _render_bulk_move(api, selected, own_files, sibling_folders)

    if not _SORTABLES_AVAILABLE:
        st.caption(
            "Drag-drop is in fallback mode. Run `uv sync` from `apps/console-streamlit/` on a networked host to enable bulk move."
        )


main()
