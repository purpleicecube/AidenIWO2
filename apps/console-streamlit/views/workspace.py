"""Workspace — Loop δ.4 real operator workspace.

Replaces the γ.5 recent-activity placeholder with the real per-tenant
folder/file environment per CODEX directive § Stage 1. Reads the tree
from `GET /workspace/tree`; writes via the CRUD routes from δ.2.

Drag-drop posture:
- If `streamlit_sortables` is importable, file moves use literal
  HTML5 drag-and-drop between per-folder lists.
- If not importable (e.g. offline install), the page falls back to
  an explicit "Move to…" action on each card. Functionally
  equivalent for keyboard-driven operation.

Both paths preserve the same backend audit shape: every move emits
`file.moved` or `folder.moved` via the CRUD route.
"""

from __future__ import annotations

import base64
from datetime import datetime
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


_SS_TREE = "iwo3_workspace_tree_cache"
_SS_FOCUS_FOLDER = "workspace_focus_folder_id"


def _ts(value: object) -> str:
    if not value:
        return "-"
    return str(value).replace("T", " ").replace("+00:00", " UTC")


def _humanise_size(text: Optional[str]) -> str:
    if not text:
        return "-"
    n = len(text)
    if n < 1024:
        return f"{n} B"
    if n < 1_048_576:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1_048_576:.2f} MB"


def _fetch_tree(api) -> dict[str, Any]:
    """Always-fresh tree; `api.list_*` calls are cheap on the local DB."""
    return api._request("GET", "/workspace/tree")  # type: ignore[attr-defined]


def _children_by_parent(folders: list[dict]) -> dict[str | None, list[dict]]:
    out: dict[str | None, list[dict]] = {}
    for f in folders:
        out.setdefault(f.get("parent_folder_id"), []).append(f)
    return out


def _files_by_folder(files: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for fi in files:
        if fi.get("workspace_folder_id"):
            out.setdefault(fi["workspace_folder_id"], []).append(fi)
    return out


def _folder_label(folder: dict) -> str:
    return "📁 /" if folder.get("is_root") else f"📁 {folder['name']}"


def _file_emoji(mime: Optional[str]) -> str:
    if not mime:
        return "📄"
    if mime.startswith("image/"):
        return "🖼️"
    if "pdf" in mime:
        return "📕"
    if "presentation" in mime or mime.endswith("pptx"):
        return "📊"
    if "markdown" in mime or mime.endswith("md"):
        return "📝"
    if "json" in mime:
        return "🔧"
    if "csv" in mime:
        return "📈"
    return "📄"


# ── Sidebar tree navigation ───────────────────────────────────────────


def _render_tree_sidebar(
    api,
    tree: dict[str, Any],
    *,
    selected_id: str,
) -> str:
    """Recursively render the folder tree as nested checkboxes-ish
    radio. Returns the new selected folder id."""
    folders = tree["folders"]
    children = _children_by_parent(folders)
    root = next(f for f in folders if f.get("is_root"))

    st.markdown("**Folders**")

    # Build a flat list of (depth, folder) entries for Streamlit's radio.
    flat: list[tuple[int, dict]] = []

    def walk(node, depth):
        flat.append((depth, node))
        for c in sorted(children.get(node["id"], []), key=lambda f: f["name"]):
            walk(c, depth + 1)

    walk(root, 0)

    options = [f["id"] for _, f in flat]
    labels = {
        f["id"]: ("  " * d) + _folder_label(f)
        for d, f in flat
    }
    if selected_id not in options:
        selected_id = root["id"]
    chosen = st.radio(
        "Pick a folder",
        options,
        index=options.index(selected_id),
        format_func=lambda fid: labels.get(fid, fid),
        key="workspace-folder-radio",
        label_visibility="collapsed",
    )
    return chosen


# ── New folder + new file forms ───────────────────────────────────────


def _render_new_folder_form(api, parent_id: str) -> None:
    with st.form(f"newfolder-{parent_id}", clear_on_submit=True):
        name = st.text_input("New folder name", placeholder="e.g. Drafts")
        submit = st.form_submit_button("Create folder")
        if submit and name.strip():
            try:
                api._request(
                    "POST",
                    "/workspace/folders",
                    json={"parent_folder_id": parent_id, "name": name.strip()},
                )
                st.success(f"Created folder `{name}`.")
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")


def _render_new_file_form(api, parent_id: str) -> None:
    with st.form(f"newfile-{parent_id}", clear_on_submit=True):
        col1, col2 = st.columns([2, 1])
        with col1:
            filename = st.text_input(
                "Filename", placeholder="notes.md"
            )
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
        submit = st.form_submit_button("Create file")
        if submit and filename.strip():
            payload: dict[str, Any] = {
                "workspace_folder_id": parent_id,
                "filename": filename.strip(),
                "mime_type": mime,
            }
            if upload is not None:
                payload["mime_type"] = upload.type or mime
                payload["content_b64"] = base64.b64encode(
                    upload.getvalue()
                ).decode("ascii")
            else:
                payload["content_text"] = text
            try:
                api._request("POST", "/workspace/files", json=payload)
                st.success(f"Created file `{filename}`.")
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")


# ── Folder + file action menus ────────────────────────────────────────


def _move_target_options(
    folders: list[dict], current_folder_id: str, exclude_self: Optional[str] = None
) -> list[dict]:
    """Folders the operator can move into (everything except the current
    parent and any descendant of `exclude_self` — the latter prevents
    folder-into-self moves; cycle detection is server-side too)."""
    out = []
    excluded: set[str] = set()
    if exclude_self:
        # Find descendants of exclude_self
        children = _children_by_parent(folders)
        stack = [exclude_self]
        while stack:
            cur = stack.pop()
            excluded.add(cur)
            for c in children.get(cur, []):
                stack.append(c["id"])
    for f in folders:
        if f["id"] in excluded:
            continue
        out.append(f)
    return out


def _render_folder_actions(
    api, folder: dict, all_folders: list[dict], can_write: bool, can_delete: bool
) -> None:
    if folder.get("is_root"):
        return
    with st.expander(f"Actions for `{folder['name']}`", expanded=False):
        cols = st.columns(2)
        with cols[0]:
            new_name = st.text_input(
                "Rename to",
                value=folder["name"],
                key=f"ren-{folder['id']}",
            )
            if st.button(
                "Rename",
                key=f"renbtn-{folder['id']}",
                disabled=(not can_write or new_name.strip() == folder["name"]),
            ):
                try:
                    api._request(
                        "PATCH",
                        f"/workspace/folders/{folder['id']}",
                        json={"name": new_name.strip()},
                    )
                    st.success("Renamed.")
                    st.rerun()
                except APIError as err:
                    st.error(f"❌ {err.detail}")
        with cols[1]:
            targets = _move_target_options(
                all_folders, folder["id"], exclude_self=folder["id"]
            )
            target_id = st.selectbox(
                "Move under…",
                [t["id"] for t in targets],
                format_func=lambda tid: next(
                    (
                        ("/" if t.get("is_root") else t["name"])
                        for t in targets
                        if t["id"] == tid
                    ),
                    tid,
                ),
                key=f"mv-{folder['id']}",
            )
            if st.button(
                "Move", key=f"mvbtn-{folder['id']}", disabled=not can_write
            ):
                try:
                    api._request(
                        "PATCH",
                        f"/workspace/folders/{folder['id']}",
                        json={"parent_folder_id": target_id},
                    )
                    st.success("Moved.")
                    st.rerun()
                except APIError as err:
                    st.error(f"❌ {err.detail}")
        if st.button(
            f"🗑️ Delete `{folder['name']}`",
            key=f"del-{folder['id']}",
            disabled=not can_delete,
            help=(
                None
                if can_delete
                else "Requires workspace:delete (admin/owner)"
            ),
        ):
            try:
                api._request("DELETE", f"/workspace/folders/{folder['id']}")
                st.success("Deleted.")
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.detail}")


def _render_file_actions(
    api, file: dict, all_folders: list[dict], can_write: bool, can_delete: bool
) -> None:
    with st.expander(
        f"Actions for `{file.get('filename') or file['id'][:8]}`",
        expanded=False,
    ):
        cols = st.columns(2)
        with cols[0]:
            new_name = st.text_input(
                "Rename to",
                value=file.get("filename") or "",
                key=f"f-ren-{file['id']}",
            )
            if st.button(
                "Rename",
                key=f"f-renbtn-{file['id']}",
                disabled=(not can_write or new_name.strip() == (file.get("filename") or "")),
            ):
                try:
                    api._request(
                        "PATCH",
                        f"/workspace/files/{file['id']}",
                        json={"filename": new_name.strip()},
                    )
                    st.success("Renamed.")
                    st.rerun()
                except APIError as err:
                    st.error(f"❌ {err.detail}")
        with cols[1]:
            targets = all_folders
            target_id = st.selectbox(
                "Move to…",
                [t["id"] for t in targets],
                format_func=lambda tid: next(
                    (
                        ("/" if t.get("is_root") else t["name"])
                        for t in targets
                        if t["id"] == tid
                    ),
                    tid,
                ),
                key=f"f-mv-{file['id']}",
            )
            if st.button(
                "Move",
                key=f"f-mvbtn-{file['id']}",
                disabled=not can_write,
            ):
                try:
                    api._request(
                        "PATCH",
                        f"/workspace/files/{file['id']}",
                        json={"workspace_folder_id": target_id},
                    )
                    st.success("Moved.")
                    st.rerun()
                except APIError as err:
                    st.error(f"❌ {err.detail}")
        if st.button(
            f"🗑️ Remove from workspace",
            key=f"f-del-{file['id']}",
            disabled=not can_delete,
            help=(
                None
                if can_delete
                else "Requires workspace:delete (admin/owner)"
            ),
        ):
            try:
                api._request("DELETE", f"/workspace/files/{file['id']}")
                st.success("Removed.")
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.detail}")


# ── File preview ─────────────────────────────────────────────────────


def _fetch_file_preview(api, file_id: str) -> Optional[dict[str, Any]]:
    """Fetch a single artifact row to render content. Reuses the
    existing artifacts surface — no new endpoint needed because the
    list /workspace/tree already returns storage_ref + filename, and
    we don't expose extracted_text in the tree response. For a
    preview, fetch the artifact row directly via the bypass endpoint
    in /workspace if Beta needs it. For Loop δ we render whatever
    the tree row carries."""
    return None  # placeholder for Beta — see comment


def _render_file_preview(file: dict) -> None:
    mime = file.get("mime_type") or ""
    storage_ref = file.get("storage_ref") or ""
    if storage_ref.startswith("output_package://"):
        st.caption(
            f"This file came from output package "
            f"`{storage_ref.removeprefix('output_package://')}`. "
            "Use Output Packages for the full deliverable."
        )
        return
    if storage_ref.startswith("inline://workspace"):
        st.caption(
            "Inline workspace content. "
            "Open via API to read full text."
        )
        return
    st.caption(f"Storage ref: `{storage_ref}`")


# ── Drag-drop file move (when streamlit-sortables loaded) ────────────


def _render_dragdrop_panel(
    api,
    folder: dict,
    files: list[dict],
    sibling_folders: list[dict],
) -> None:
    """When `streamlit-sortables` is available, render the current
    folder's files plus its siblings as a multi-list sortable. Moving a
    card between lists fires PATCH /workspace/files/{id} with the new
    folder id."""
    if not _SORTABLES_AVAILABLE or _sort_items is None:
        return
    # Build buckets: current folder + each sibling.
    items: list[dict[str, Any]] = [
        {
            "header": _folder_label(folder),
            "items": [
                f"{_file_emoji(f.get('mime_type'))} {f.get('filename') or f['id'][:8]}::{f['id']}"
                for f in files
            ],
        }
    ]
    sibling_id_by_label: dict[str, str] = {
        _folder_label(sf): sf["id"] for sf in sibling_folders
    }
    for sf in sibling_folders:
        items.append({"header": _folder_label(sf), "items": []})

    sorted_state = _sort_items(
        items,
        multi_containers=True,
        direction="vertical",
        key=f"workspace-dragdrop-{folder['id']}",
    )
    if not sorted_state:
        return
    # Detect any moved file: in the new state's first bucket (current folder)
    # we should still see all files; if a file appears in a sibling bucket,
    # PATCH it.
    for bucket in sorted_state:
        target_label = bucket.get("header")
        target_id = sibling_id_by_label.get(target_label)
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
            except APIError:
                pass


# ── Main page ────────────────────────────────────────────────────────


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Workspace</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          The tenant's structured landing zone. Outputs auto-save here
          under `Outputs/`; you can organise folders and files freely.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        tree = _fetch_tree(api)
        can_write = api.check_permission("workspace:write").allowed
        can_delete = api.check_permission("workspace:delete").allowed
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    folders: list[dict] = tree["folders"]
    files: list[dict] = tree["files"]
    if not folders:
        st.warning(
            "No workspace folders for this tenant. Run the seed loader "
            "(`bash infra/local/seed-iwo3.sh`) — every active tenant "
            "should have a `/` root + `Outputs/` child."
        )
        return

    children_map = _children_by_parent(folders)
    files_map = _files_by_folder(files)
    by_id = {f["id"]: f for f in folders}

    # Default focus = pop session-state if set, else root.
    focus = st.session_state.pop(_SS_FOCUS_FOLDER, None)
    root_id = next(f["id"] for f in folders if f.get("is_root"))
    selected_id = focus or root_id

    sidebar, main_pane = st.columns([1, 3])
    with sidebar:
        selected_id = _render_tree_sidebar(api, tree, selected_id=selected_id)

    selected = by_id.get(selected_id)
    with main_pane:
        if not selected:
            st.info("Select a folder.")
            return

        # Header block
        crumbs = []
        cur = selected
        while cur:
            crumbs.append("/" if cur.get("is_root") else cur["name"])
            cur = by_id.get(cur.get("parent_folder_id")) if cur.get("parent_folder_id") else None
        crumbs.reverse()
        st.markdown(f"### {' / '.join(crumbs)}")
        st.caption(
            f"Folder id `{selected['id'][:8]}…` · "
            f"created {_ts(selected.get('created_at'))} · "
            f"sortables {'✅' if _SORTABLES_AVAILABLE else 'fallback (move via dropdown)'}"
        )

        children = sorted(
            children_map.get(selected_id, []), key=lambda f: f["name"]
        )
        own_files = sorted(
            files_map.get(selected_id, []),
            key=lambda f: f.get("filename") or "",
        )

        # Top action row
        with st.expander("➕ New folder / file in this folder", expanded=False):
            tab_folder, tab_file = st.tabs(["New folder", "New file"])
            with tab_folder:
                _render_new_folder_form(api, selected_id)
            with tab_file:
                _render_new_file_form(api, selected_id)

        if not children and not own_files:
            st.info(
                "This folder is empty. Use the New folder / New file form "
                "above, or run a work order — outputs auto-save to "
                "`Outputs/` and you can move them here."
            )

        # Children (subfolders)
        if children:
            st.markdown("**Subfolders**")
            for child in children:
                cnt_files = len(files_map.get(child["id"], []))
                cnt_subs = len(children_map.get(child["id"], []))
                st.markdown(
                    f"- {_folder_label(child)} · "
                    f"{cnt_subs} subfolder(s) · {cnt_files} file(s)"
                )
                _render_folder_actions(
                    api, child, folders, can_write, can_delete
                )

        # Files in this folder
        if own_files:
            st.markdown("**Files**")
            for f in own_files:
                emoji = _file_emoji(f.get("mime_type"))
                fname = f.get("filename") or f["id"][:8]
                st.markdown(
                    f"- {emoji} **{fname}** · `{f.get('mime_type') or '-'}` "
                    f"· source `{f.get('source_type')}`"
                )
                _render_file_actions(api, f, folders, can_write, can_delete)
                _render_file_preview(f)

            # Drag-drop pane (literal HTML5 when sortables available)
            sibling_folders = [
                sf for sf in folders
                if sf["id"] != selected_id and sf.get("parent_folder_id") == selected.get("parent_folder_id")
            ]
            if sibling_folders and _SORTABLES_AVAILABLE:
                st.markdown(
                    "**Drag-drop move** — drag a file card between lists "
                    "to move it."
                )
                _render_dragdrop_panel(api, selected, own_files, sibling_folders)

    if not _SORTABLES_AVAILABLE:
        st.caption(
            "💡 Drag-and-drop is in fallback mode. Install "
            "`streamlit-sortables` (run `uv sync` from "
            "`apps/console-streamlit/`) for literal drag-drop."
        )


main()
