"""Workspace — IWO2 visual idiom matched to client/src/pages/workspace.tsx.

Architect lock 2026-04-26 §D2 (`IWO3_DESIGN_MEGALOOP_ARCHITECT_LOCK_v0.1.0`):
visual parity first, backend parity preserved, abstraction deferred.

v3 (post second-render review):
  - Card chrome via `st.container(border=True)` instead of raw HTML
    anchor (Streamlit's sanitizer was disrupting `<a>` with block-level
    children, splitting the card visual into stacked rectangles).
  - SVG icons rendered via st.markdown (Streamlit preserves inline SVG
    inside markdown blocks but not inside anchors).
  - The card name is itself a Streamlit button styled as a clickable
    title (no border, transparent background, primary color on hover).
    The icon and description are visual chrome; clicking the title
    navigates / opens preview.
  - Popover dropdown caret hidden via CSS so the ⋮ button reads as a
    single glyph (matches IWO2 hover-revealed menu indicator).
  - Drag-drop offline state surfaced as a primary banner (R-034 carry).

Backend wiring unchanged from v1/v2: every action calls FastAPI;
workspace:write/delete still cosmetic-gated; server enforces.

Known parity gap: in-place file edit (architect lock §5 forbids the
backend PUT this loop). Preview-only.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def _resolve_sandbox_base_url() -> tuple[str, str]:
    """Return (base_url, source) for the canonical Node sandbox surface.
    Mirrors views/sandbox.py logic so the workspace handoff lands on
    the same URL operators see on the launcher page.
    """
    env_url = os.environ.get("IWO3_SANDBOX_URL") or os.environ.get(
        "IWO3_NODE_BASE_URL"
    )
    if env_url:
        return env_url.rstrip("/"), "env"
    return "http://localhost:5050", "local-default"


try:
    from streamlit_sortables import sort_items as _sort_items
    _SORTABLES_AVAILABLE = True
except Exception:  # noqa: BLE001 — optional dep, R-034 carry
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


# ── Lucide-style inline SVG icons ────────────────────────────────────
# Path data sourced from Lucide (MIT). 24x24 viewBox, stroke-based.

_PATHS = {
    "folder": (
        '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9'
        'L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'
    ),
    "folder_lock": (
        '<path d="M20 12V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9L7.74 3.9'
        'A2 2 0 0 0 6.07 3H2a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h6.5"/>'
        '<rect x="14" y="14" width="8" height="6" rx="1"/>'
        '<path d="M16 14v-2a2 2 0 1 1 4 0v2"/>'
    ),
    "file": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
    ),
    "file_text": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>'
    ),
    "file_json": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M10 12a1 1 0 0 0-1 1v1a2 2 0 0 1-2 2 2 2 0 0 1 2 2v1a1 1 0 0 0 1 1"/>'
        '<path d="M14 18a1 1 0 0 0 1-1v-1a2 2 0 0 1 2-2 2 2 0 0 1-2-2v-1a1 1 0 0 0-1-1"/>'
    ),
    "file_code": (
        '<path d="M10 12.5 8 15l2 2.5"/><path d="m14 12.5 2 2.5-2 2.5"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
    ),
    "file_image": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<circle cx="10" cy="13" r="2"/>'
        '<path d="m20 17-1.296-1.296a2.41 2.41 0 0 0-3.408 0L9 22"/>'
    ),
    "file_spreadsheet": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M8 13h2"/><path d="M14 13h2"/>'
        '<path d="M8 17h2"/><path d="M14 17h2"/>'
    ),
    "presentation": (
        '<path d="M2 3h20"/>'
        '<path d="M21 3v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3"/>'
        '<path d="m7 21 5-5 5 5"/><path d="M12 16v5"/>'
    ),
    "globe": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'
        '<path d="M2 12h20"/>'
    ),
    "chevron_right": (
        '<path d="m9 18 6-6-6-6"/>'
    ),
    "home": (
        '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        '<path d="M9 22V12h6v10"/>'
    ),
}


def _svg(name: str, *, size: int = 36, color: Optional[str] = None) -> str:
    body = _PATHS.get(name, _PATHS["file"])
    style = f' style="color:{color};"' if color else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"{style}>{body}</svg>'
    )


def _file_icon_name(file_row: dict[str, Any]) -> str:
    mime = (file_row.get("mime_type") or "").lower()
    filename = (file_row.get("filename") or "").lower()
    source_type = file_row.get("source_type") or ""
    if filename.startswith("preview:") or source_type == "external_preview":
        return "globe"
    if "json" in mime or filename.endswith(".json"):
        return "file_json"
    if "javascript" in mime or "typescript" in mime or filename.endswith((".js", ".ts", ".tsx", ".jsx", ".py", ".css")):
        return "file_code"
    if mime.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return "file_image"
    if "spreadsheet" in mime or "excel" in mime or filename.endswith((".xlsx", ".xls", ".csv")):
        return "file_spreadsheet"
    if "presentation" in mime or "powerpoint" in mime or filename.endswith((".pptx", ".ppt")):
        return "presentation"
    if "html" in mime or filename.endswith((".html", ".htm")):
        return "globe"
    if "markdown" in mime or "text" in mime or filename.endswith((".md", ".txt", ".log", ".pdf")):
        return "file_text"
    return "file"


def _folder_icon_name(folder: dict[str, Any]) -> str:
    if folder.get("owner_user_id"):
        return "folder_lock"
    return "folder"


def _folder_hint(folder: dict[str, Any]) -> str:
    if folder.get("is_root"):
        return "Tenant root for plans, artifacts, and deliverables."
    if folder.get("owner_user_id"):
        return _FOLDER_HINTS.get(folder.get("name") or "", "Private draft area visible only to you")
    return _FOLDER_HINTS.get(folder.get("name") or "", "")


def _humanise_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1_048_576:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1_048_576:.2f} MB"


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
    st.session_state.pop(_SS_PREVIEW_FILE, None)


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


# ── Header ───────────────────────────────────────────────────────────


def _render_breadcrumb(lineage: list[dict[str, Any]]) -> None:
    """IWO2-style chevron-separated breadcrumb."""
    parts: list[str] = []
    home_span = '<span class="ws-crumb-home">' + _svg("home", size=14) + "</span>"
    chevron = '<span class="ws-crumb-sep">' + _svg("chevron_right", size=12) + "</span>"
    for idx, folder in enumerate(lineage):
        label = "Workspace" if folder.get("is_root") else folder["name"]
        prefix = home_span if idx == 0 else ""
        if idx == len(lineage) - 1:
            parts.append(f'<span class="ws-crumb ws-crumb-current">{prefix}{label}</span>')
        else:
            parts.append(
                f'<span class="ws-crumb ws-crumb-link" data-folder-id="{folder["id"]}">'
                f'{prefix}{label}</span>'
            )
        if idx < len(lineage) - 1:
            parts.append(chevron)
    st.markdown(f'<div class="ws-crumb-row">{"".join(parts)}</div>', unsafe_allow_html=True)


def _render_breadcrumb_buttons(lineage: list[dict[str, Any]]) -> None:
    """Hidden Streamlit buttons that capture clicks for crumbs >0; the
    visual breadcrumb above is markdown-only. The breadcrumb HTML cannot
    fire Streamlit reruns, so we mirror it with real buttons rendered
    just below — CSS hides them in a way that keeps them keyboard-
    reachable."""
    if len(lineage) <= 1:
        return
    cols = st.columns(len(lineage) - 1 + [4][0:1] + [1] * 0 or [1] * (len(lineage) - 1))
    for idx, folder in enumerate(lineage[:-1]):
        label = "Workspace" if folder.get("is_root") else folder["name"]
        with cols[idx]:
            if st.button(
                f"⤴ {label}",
                key=f"ws-crumb-btn-{folder['id']}",
                use_container_width=True,
            ):
                _set_focus(folder["id"])
                st.rerun()


def _render_new_popover(api, parent_id: str, scratch: Optional[dict[str, Any]], can_write: bool) -> None:  # noqa: ANN001
    popover = getattr(st, "popover", None)
    label = "+ New"
    if popover is None:
        with st.expander(label, expanded=False):
            _render_new_menu_body(api, parent_id, scratch, can_write)
        return
    with popover(label, use_container_width=True, disabled=not can_write):
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
        st.caption("Your private scratch folder is visible only to you.")
        if st.button("Open my scratch", use_container_width=True, type="primary", key="ws-scratch-open"):
            _set_focus(scratch["id"])
            st.rerun()
        return
    st.caption("Per-operator scratch is private — only you see it.")
    if st.button("Create my scratch folder", use_container_width=True, type="primary", key="ws-scratch-create"):
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
    cols = st.columns([8, 1, 1])
    with cols[0]:
        _render_breadcrumb(lineage)
        # Mirror clickable crumbs as small buttons (markdown crumbs can't
        # fire reruns); CSS demotes these so they appear as a quiet row.
        if len(lineage) > 1:
            crumb_cols = st.columns(len(lineage) - 1)
            for idx, folder in enumerate(lineage[:-1]):
                with crumb_cols[idx]:
                    label = "Workspace" if folder.get("is_root") else folder["name"]
                    if st.button(
                        f"↑ {label}",
                        key=f"ws-crumb-btn-{folder['id']}",
                        use_container_width=True,
                    ):
                        _set_focus(folder["id"])
                        st.rerun()
    with cols[1]:
        parent_id = selected.get("parent_folder_id")
        if st.button(
            "← Back",
            use_container_width=True,
            disabled=parent_id is None,
            key="ws-toolbar-up",
        ):
            _set_focus(parent_id or root_id)
            st.rerun()
    with cols[2]:
        _render_new_popover(api, selected["id"], scratch, can_write)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Card grid ────────────────────────────────────────────────────────


def _render_folder_card(
    folder: dict[str, Any],
    *,
    child_count: int,
    file_count: int,
    api,  # noqa: ANN001
    all_folders: list[dict[str, Any]],
    can_write: bool,
    can_delete: bool,
) -> None:
    icon_name = _folder_icon_name(folder)
    title = "Workspace" if folder.get("is_root") else folder["name"]
    desc = _folder_hint(folder)
    chips: list[str] = []
    if child_count:
        chips.append(f"{child_count} folder{'s' if child_count != 1 else ''}")
    if file_count:
        chips.append(f"{file_count} file{'s' if file_count != 1 else ''}")
    if folder.get("owner_user_id"):
        chips.append("private")
    chip_text = " · ".join(chips) if chips else "Empty"
    icon_color = "#1E5F91"

    with st.container(border=True):
        st.markdown(
            f'<div class="ws-card-icon">{_svg(icon_name, size=36, color=icon_color)}</div>',
            unsafe_allow_html=True,
        )
        # Name as the primary click target; tertiary button renders as a
        # borderless link-style action — closest Streamlit gets to IWO2's
        # plain-text-clickable card title.
        if st.button(
            title,
            key=f"ws-folder-open-{folder['id']}",
            use_container_width=True,
            type="tertiary",
        ):
            _set_focus(folder["id"])
            st.rerun()
        st.markdown(
            f'<div class="ws-card-desc">{desc or "&nbsp;"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="ws-card-chip">{chip_text}</div>',
            unsafe_allow_html=True,
        )
        if not folder.get("is_root"):
            _render_folder_overflow(api, folder, all_folders, can_write, can_delete)


def _render_file_card(
    file_row: dict[str, Any],
    *,
    api,  # noqa: ANN001
    all_folders: list[dict[str, Any]],
    can_write: bool,
    can_delete: bool,
) -> None:
    icon_name = _file_icon_name(file_row)
    name = file_row.get("filename") or file_row["id"][:8]
    desc = file_row.get("mime_type") or "File"
    icon_color = "#94a3b8"

    with st.container(border=True):
        st.markdown(
            f'<div class="ws-card-icon">{_svg(icon_name, size=36, color=icon_color)}</div>',
            unsafe_allow_html=True,
        )
        if st.button(
            name,
            key=f"ws-file-open-{file_row['id']}",
            use_container_width=True,
            type="tertiary",
        ):
            _set_preview(file_row["id"])
            st.rerun()
        st.markdown(
            f'<div class="ws-card-desc">{desc}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="ws-card-chip">source {file_row.get("source_type") or "—"}</div>',
            unsafe_allow_html=True,
        )
        _render_file_overflow(api, file_row, all_folders, can_write, can_delete)


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
            f"""
            <div class="ws-empty">
              <div class="ws-empty-icon">{_svg("folder", size=64, color="#cbd5e1")}</div>
              <div class="ws-empty-title">Empty folder</div>
              <div class="ws-empty-body">Create a folder or file with the New menu, or move outputs here from <code>Outputs/</code>.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    cols_per_row = 6 if len(items) >= 6 else max(1, len(items))
    for start in range(0, len(items), cols_per_row):
        cols = st.columns(cols_per_row, gap="small")
        for col, (kind, payload) in zip(cols, items[start:start + cols_per_row]):
            with col:
                if kind == "folder":
                    sub_count = len(children_map.get(payload["id"], []))
                    file_count = len(files_map.get(payload["id"], []))
                    _render_folder_card(
                        payload,
                        child_count=sub_count,
                        file_count=file_count,
                        api=api,
                        all_folders=all_folders,
                        can_write=can_write,
                        can_delete=can_delete,
                    )
                else:
                    _render_file_card(
                        payload,
                        api=api,
                        all_folders=all_folders,
                        can_write=can_write,
                        can_delete=can_delete,
                    )


def _render_folder_overflow(
    api,  # noqa: ANN001
    folder: dict[str, Any],
    all_folders: list[dict[str, Any]],
    can_write: bool,
    can_delete: bool,
) -> None:
    popover = getattr(st, "popover", None)
    if popover is None:
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
            f"Delete `{folder['name']}`",
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


def _render_file_overflow(
    api,  # noqa: ANN001
    file_row: dict[str, Any],
    all_folders: list[dict[str, Any]],
    can_write: bool,
    can_delete: bool,
) -> None:
    popover = getattr(st, "popover", None)
    if popover is None:
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
        sandbox_base, sandbox_source = _resolve_sandbox_base_url()
        sandbox_url = f"{sandbox_base}/sandbox?source={file_row['id']}"
        st.link_button(
            "Review in Sandbox ↗",
            sandbox_url,
            use_container_width=True,
        )
        if sandbox_source == "local-default":
            st.caption(
                "Opens the local Node sandbox (set `IWO3_SANDBOX_URL` for hosted)."
            )
        else:
            st.caption("Opens the canonical Node sandbox in a new tab.")

        st.divider()
        if st.button(
            "Remove from workspace",
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


# ── Preview pane ─────────────────────────────────────────────────────


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
    icon = _svg(_file_icon_name(file_row), size=18, color="#94a3b8")

    st.markdown('<div class="ws-preview">', unsafe_allow_html=True)
    header_cols = st.columns([6, 1])
    with header_cols[0]:
        st.markdown(
            f"""
            <div class="ws-preview-title">
              <span class="ws-preview-icon">{icon}</span>
              <span class="ws-preview-title-name">{name}</span>
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

    payload = content.get("content")
    if encoding == "utf-8":
        if "json" in mime:
            st.code(payload or "", language="json")
        elif "markdown" in mime or (file_row.get("filename") or "").lower().endswith(".md"):
            st.code(payload or "", language="markdown")
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
    st.markdown("</div>", unsafe_allow_html=True)


# ── Drag-drop status banner ──────────────────────────────────────────


def _render_dragdrop_status() -> None:
    if _SORTABLES_AVAILABLE:
        return
    st.caption(
        "**Drag-drop disabled.** `streamlit-sortables` is not installed in this venv "
        "(R-034 carry — PyPI is unreachable from the offline sandbox). Use the ⋮ menu "
        "on each card for moves. To enable, run on a networked host: "
        "`cd apps/console-streamlit && uv add streamlit-sortables`."
    )


# ── CSS ──────────────────────────────────────────────────────────────


def _inject_css() -> None:
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

        /* Toolbar — breadcrumb on left, Back + New on right */
        .ws-toolbar { margin-bottom: 0.5rem; }
        .ws-crumb-row {
          display: flex; align-items: center; gap: 0.3rem;
          flex-wrap: wrap;
          font-size: 0.86rem;
          padding: 0.35rem 0;
        }
        .ws-crumb {
          display: inline-flex; align-items: center; gap: 0.3rem;
          color: var(--ws-muted);
          padding: 0.2rem 0.4rem;
          border-radius: 4px;
        }
        .ws-crumb-current {
          color: var(--ws-text);
          font-weight: 500;
        }
        .ws-crumb-link {
          color: var(--ws-muted);
        }
        .ws-crumb-home { display: inline-flex; align-items: center; }
        .ws-crumb-sep {
          display: inline-flex; align-items: center;
          color: var(--ws-muted-soft);
        }

        /* Toolbar — make the New popover read as a primary action;
           keep Back compact and quiet. */
        .ws-toolbar div[data-testid="stPopover"] > button {
          border-radius: 4px;
          background: var(--ws-primary);
          color: #ffffff;
          border: 1px solid var(--ws-primary);
          font-weight: 500;
          font-size: 0.86rem;
          padding: 0.35rem 0.85rem;
          min-height: 2.1rem;
        }
        .ws-toolbar div[data-testid="stPopover"] > button:hover {
          background: #174c75;
          border-color: #174c75;
        }
        .ws-toolbar div[data-testid="stButton"] > button {
          border-radius: 4px;
          font-size: 0.86rem;
          font-weight: 500;
          min-height: 2.1rem;
          padding: 0.35rem 0.7rem;
          border: 1px solid var(--ws-border);
          background: var(--ws-surface);
          color: var(--ws-text);
        }

        /* Cards — every st.container(border=True) on this page is a
           workspace card. Tight, IWO2-shaped. Fixed min-height so cards
           with and without descriptions align in the same row. */
        div[data-testid="stVerticalBlockBorderWrapper"] {
          border: 1px solid var(--ws-border) !important;
          border-radius: 6px !important;
          background: var(--ws-surface) !important;
          padding: 1rem 0.6rem 0.6rem 0.6rem !important;
          transition: border-color 150ms ease, box-shadow 150ms ease, background 150ms ease;
          min-height: 168px;
          height: 100%;
          display: flex;
          flex-direction: column;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {
          border-color: var(--ws-primary);
          background: var(--ws-surface-alt);
          box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
        }
        /* Inner stVerticalBlock fills the card */
        div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {
          flex: 1;
          display: flex;
          flex-direction: column;
        }

        .ws-card-icon {
          display: flex; align-items: center; justify-content: center;
          line-height: 0;
          margin-bottom: 0.3rem;
        }
        .ws-card-icon svg { display: block; }
        .ws-card-desc {
          font-size: 0.7rem;
          color: var(--ws-muted);
          line-height: 1.3;
          text-align: center;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
          margin-top: 0.1rem;
          min-height: 1.85em;
          padding: 0 0.25rem;
        }
        .ws-card-chip {
          font-size: 0.66rem;
          color: var(--ws-muted-soft);
          text-align: center;
          margin-top: auto;
          padding-top: 0.3rem;
        }

        /* Card name (tertiary button) — Streamlit renders tertiary
           buttons as link-style; we further reset to fully match an
           IWO2 plain-text card title. Triple-targeted to win the
           specificity battle against Streamlit's default button rules. */
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="tertiary"],
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button.st-emotion-cache-* {
          border: none !important;
          background: transparent !important;
          color: var(--ws-text) !important;
          font-size: 0.84rem !important;
          font-weight: 600 !important;
          line-height: 1.3 !important;
          padding: 0.1rem 0.25rem !important;
          min-height: auto !important;
          height: auto !important;
          text-align: center !important;
          box-shadow: none !important;
          word-break: break-word !important;
          transition: color 150ms ease !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="tertiary"]:hover,
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="tertiary"]:focus,
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="tertiary"]:active {
          color: var(--ws-primary) !important;
          background: transparent !important;
          border: none !important;
          outline: none !important;
          box-shadow: none !important;
        }
        /* Inner div padding from Streamlit button label wrapper */
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stButton"] > button[kind="tertiary"] > div {
          padding: 0 !important;
          margin: 0 !important;
        }

        /* Card ⋮ popover — small, secondary, no caret indicator */
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stPopover"] {
          margin-top: 0.25rem;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stPopover"] > button {
          border-radius: 4px !important;
          font-size: 0.9rem !important;
          font-weight: 600 !important;
          padding: 0.05rem 0.25rem !important;
          min-height: 1.5rem !important;
          height: 1.5rem !important;
          border: 1px solid transparent !important;
          background: transparent !important;
          color: var(--ws-muted-soft) !important;
          letter-spacing: 0 !important;
          box-shadow: none !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stPopover"] > button:hover {
          color: var(--ws-primary) !important;
          background: var(--ws-primary-soft) !important;
          border-color: var(--ws-border) !important;
        }
        /* Hide every visual indicator inside the popover button except
           our ⋮ glyph: the dropdown caret SVG, any after/before glyphs,
           and any extra spans Streamlit injects. */
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stPopover"] button svg,
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stPopover"] button [data-testid*="icon" i],
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stPopover"] button > div > div + div,
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stPopover"] button > div > span + span {
          display: none !important;
        }

        /* Empty state */
        .ws-empty {
          padding: 3rem 1rem 3.2rem 1rem;
          text-align: center;
          color: var(--ws-muted);
        }
        .ws-empty-icon { margin-bottom: 0.7rem; line-height: 0; display: inline-block; }
        .ws-empty-title { font-size: 1rem; font-weight: 600; color: var(--ws-text); margin-bottom: 0.4rem; }
        .ws-empty-body { font-size: 0.84rem; max-width: 32rem; margin: 0 auto; line-height: 1.5; }

        /* Preview pane */
        .ws-preview { margin-top: 1rem; }
        .ws-preview-title {
          font-size: 0.9rem;
          font-weight: 600;
          color: var(--ws-text);
          display: flex; align-items: center; gap: 0.45rem;
          min-width: 0;
          padding: 0.65rem 0 0.45rem 0;
        }
        .ws-preview-icon { display: inline-flex; }
        .ws-preview-title-name {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 32rem;
        }
        .ws-preview-meta {
          padding: 0.6rem 0.85rem;
          border: 1px solid var(--ws-border);
          border-radius: 6px;
          background: var(--ws-surface);
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 0.25rem 1rem;
          font-size: 0.72rem;
          margin-bottom: 0.65rem;
        }
        .ws-meta-label { color: var(--ws-muted); }
        .ws-meta-value { color: var(--ws-text); }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ── Page ─────────────────────────────────────────────────────────────


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

    _render_dragdrop_status()


main()
