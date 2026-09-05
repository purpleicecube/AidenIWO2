"""Workspace tools — Aiden's hands in the tenant file tree.

WHY THIS EXISTS

The API has had full workspace folder CRUD since Loop 1
(`POST /workspace/folders`, `PATCH`/`DELETE /workspace/folders/{id}`,
`GET /workspace/tree`). Aiden's tool registry could reach none of it —
14 tools, not one touching the workspace.

So when an operator asked "create a folder named with today's date for
my outputs", Aiden had no way to do it and no way to say so. He did the
only thing he can do: raised a work order. Paul then produced a
**Markdown document titled "Deployment Report" describing a folder
creation** and filed it next to the real deliverables. Three copies of
it. No folder was ever created, and Aiden then invented URLs
(`<BASE_URL>/workspace/folder/2026-09-05`) for a folder that did not
exist, on routes that have never existed.

Two failures, one cause: an agent with no tool for a job will either
fake the job or fake the answer. These tools close the gap, and the
Tier-1 prompt gains the counterpart rule — say "I cannot" rather than
narrate a success.

SCOPE
Read + create + locate. Deliberately NOT delete or rename: an agent
that can remove an operator's folders on a misparsed instruction is a
much worse failure than one that cannot tidy up. Deletion stays a
human action in the Workspace UI.

TENANCY + PRIVACY
Every handler receives the tenant-scoped connection from
`aiden_tools.execute_tool`, so RLS confines all of it to the caller's
tenant. Nothing here takes a client_id from the model.

Tenancy is NOT sufficient on its own. `workspace_folders.owner_user_id`
marks per-operator scratch folders, which Beta-1.5 ε.5 / Q11 made
visible only to their owner — `GET /workspace/tree` filters on it and
the RLS policy does not (it checks `client_id` alone). A review on
2026-09-05 found the first cut of these tools querying by tenant only,
so Aiden could list a colleague's scratch folder, locate artifacts
inside it, and create folders beneath it. Every query below therefore
carries the same predicate as the route:

    (owner_user_id IS NULL OR owner_user_id = <actor>)

Shared folders stay visible to the tenant; someone else's scratch space
does not.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import asyncpg

from runtime.aiden_tools import ToolDefinition, ToolExecutionError
from runtime.workspace_filing import (
    ensure_child_folder,
    folder_path,
    is_valid_folder_name,
    root_folder_id,
)


_MAX_TREE_ROWS = 200

# Base URL of the operator console, e.g. http://localhost:8502.
# MUST be configured — when unset, tools return no URL at all rather
# than a guessed one. Aiden previously invented
# `<BASE_URL>/workspace/output/<id>` for routes that never existed; the
# cure for that is a real URL or none, never a plausible-looking one.
ENV_CONSOLE_BASE_URL = "IWO3_CONSOLE_BASE_URL"


def console_base_url() -> str:
    return os.environ.get(ENV_CONSOLE_BASE_URL, "").strip().rstrip("/")


def artifact_url(artifact_id: str) -> str | None:
    """Deep link that opens this document in the console's Workspace
    viewer. Returns None when no console URL is configured."""
    base = console_base_url()
    if not base or not artifact_id:
        return None
    return f"{base}/workspace?file={quote(artifact_id)}"


# Applied to every folder read/write below. Kept as one constant so a
# new query cannot quietly omit it — the invariant test asserts each
# folder query in this module carries it.
_OWNER_VISIBLE = (
    "(f.owner_user_id IS NULL OR f.owner_user_id = {actor}::uuid)"
)


async def _resolve_parent(
    conn: asyncpg.Connection, client_id: str, parent: str | None, actor: str
) -> str:
    """Resolve a parent folder given by name, path or id. Falls back to
    the tenant root. Raises rather than guessing when ambiguous."""
    root = await root_folder_id(conn, client_id)
    if not root:
        raise ToolExecutionError(
            "workspace_create_folder",
            "no_root_folder",
            "this tenant has no workspace root folder",
        )
    target = (parent or "").strip().strip("/")
    if not target:
        return root

    # Walk the path segment by segment so "Outputs/2026-09-05" works.
    current = root
    for segment in [s for s in target.split("/") if s]:
        found = await conn.fetchval(
            """
            SELECT f.id::text FROM workspace_folders f
             WHERE f.client_id = $1::uuid AND f.parent_folder_id = $2::uuid
               AND f.name = $3 AND f.deleted_at IS NULL
               AND (f.owner_user_id IS NULL OR f.owner_user_id = $4::uuid)
             LIMIT 1
            """,
            client_id,
            current,
            segment,
            actor or None,
        )
        if not found:
            raise ToolExecutionError(
                "workspace_create_folder",
                "parent_not_found",
                f"no folder '{segment}' under the path given "
                f"(looking for '{target}')",
            )
        current = found
    return current


async def _create_folder(
    conn: asyncpg.Connection, args: dict[str, Any], client_id: str
) -> dict[str, Any]:
    name = str(args.get("name", "") or "").strip()
    if not is_valid_folder_name(name):
        raise ToolExecutionError(
            "workspace_create_folder",
            "bad_args",
            "name must be 1-120 characters and contain no '/' or '\\\\' "
            f"(got {name!r}). To nest, pass `parent` separately.",
        )
    actor = str(args.get("_actor_user_id") or "").strip()
    if not actor:
        raise ToolExecutionError(
            "workspace_create_folder",
            "no_actor",
            "no authenticated actor; refusing to create a folder",
        )
    parent_id = await _resolve_parent(conn, client_id, args.get("parent"), actor)
    folder_id = await ensure_child_folder(
        conn,
        client_id=client_id,
        parent_folder_id=parent_id,
        name=name,
        created_by_user_id=actor,
    )
    return {
        "folder_id": folder_id,
        "name": name,
        "path": await folder_path(conn, client_id=client_id, folder_id=folder_id),
        "created": True,
    }


async def _list_tree(
    conn: asyncpg.Connection, args: dict[str, Any], client_id: str
) -> dict[str, Any]:
    rows = await conn.fetch(
        """
        WITH RECURSIVE down AS (
          SELECT f.id, f.parent_folder_id, f.name, f.name::text AS path,
                 0 AS depth
            FROM workspace_folders f
           WHERE f.client_id = $1::uuid AND f.parent_folder_id IS NULL
             AND f.deleted_at IS NULL
             AND (f.owner_user_id IS NULL OR f.owner_user_id = $3::uuid)
          UNION ALL
          SELECT f.id, f.parent_folder_id, f.name,
                 (CASE WHEN d.path = '/' THEN '' ELSE d.path || '/' END)
                   || f.name,
                 d.depth + 1
            FROM workspace_folders f
            JOIN down d ON f.parent_folder_id = d.id
           WHERE f.client_id = $1::uuid AND f.deleted_at IS NULL
             AND (f.owner_user_id IS NULL OR f.owner_user_id = $3::uuid)
             AND d.depth < 8
        )
        SELECT d.id::text AS id, d.path, d.depth,
               (SELECT count(*) FROM artifacts a
                 WHERE a.workspace_folder_id = d.id) AS file_count
          FROM down d
         WHERE d.path <> '/'
         ORDER BY d.path
         LIMIT $2
        """,
        client_id,
        _MAX_TREE_ROWS,
        str(args.get("_actor_user_id") or "") or None,
    )
    return {
        "folder_count": len(rows),
        "truncated": len(rows) >= _MAX_TREE_ROWS,
        "folders": [
            {
                "folder_id": r["id"],
                "path": r["path"],
                "file_count": r["file_count"],
            }
            for r in rows
        ],
    }


async def _locate_output(
    conn: asyncpg.Connection, args: dict[str, Any], client_id: str
) -> dict[str, Any]:
    """Where a produced document actually is.

    This is the tool that answers "where is the output?" — the question
    that previously drew an invented URL. Every value returned is read
    from the database.
    """
    wo = str(args.get("work_order_id", "") or "").strip()
    limit = max(1, min(int(args.get("limit", 10) or 10), 50))
    actor = str(args.get("_actor_user_id") or "") or None
    params: list[Any] = [client_id, actor]
    # An artifact inherits its folder's visibility: a document filed in
    # another operator's scratch folder must not be locatable here.
    where = (
        "a.client_id = $1::uuid AND a.workspace_folder_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM workspace_folders f "
        "WHERE f.id = a.workspace_folder_id AND f.deleted_at IS NULL "
        "AND (f.owner_user_id IS NULL OR f.owner_user_id = $2::uuid))"
    )
    if wo:
        params.append(wo)
        where += f" AND a.metadata->>'workOrderId' = ${len(params)}"
    params.append(limit)
    rows = await conn.fetch(
        f"""
        SELECT a.id::text AS artifact_id, a.filename, a.mime_type,
               a.workspace_folder_id::text AS folder_id,
               a.created_at::text AS created_at,
               a.metadata->>'outputPackageId' AS output_package_id,
               a.metadata->>'workOrderId' AS work_order_id
          FROM artifacts a
         WHERE {where}
         ORDER BY a.created_at DESC
         LIMIT ${len(params)}
        """,
        *params,
    )
    # Artifacts filed before workOrderId was recorded in metadata carry
    # no link back to their request, so a work_order_id filter returns
    # nothing for anything produced before 2026-09-05. Returning "not
    # found" there is technically true and useless — the document is
    # sitting in the workspace. Fall back to the unfiltered recent list
    # and SAY that the filter was dropped, so the answer is never
    # presented as an exact match when it is not.
    filter_relaxed = False
    if wo and not rows:
        filter_relaxed = True
        rows = await conn.fetch(
            """
            SELECT a.id::text AS artifact_id, a.filename, a.mime_type,
                   a.workspace_folder_id::text AS folder_id,
                   a.created_at::text AS created_at,
                   a.metadata->>'outputPackageId' AS output_package_id,
                   a.metadata->>'workOrderId' AS work_order_id
              FROM artifacts a
             WHERE a.client_id = $1::uuid
               AND a.workspace_folder_id IS NOT NULL
               AND EXISTS (SELECT 1 FROM workspace_folders f
                            WHERE f.id = a.workspace_folder_id
                              AND f.deleted_at IS NULL
                              AND (f.owner_user_id IS NULL
                                   OR f.owner_user_id = $2::uuid))
             ORDER BY a.created_at DESC
             LIMIT $3
            """,
            client_id,
            actor,
            limit,
        )

    out = []
    for r in rows:
        out.append(
            {
                "artifact_id": r["artifact_id"],
                "filename": r["filename"],
                "mime_type": r["mime_type"],
                # Real, clickable, opens the viewer. None when the
                # console URL is unconfigured — say so, never guess.
                "url": artifact_url(r["artifact_id"]),
                "folder_path": await folder_path(
                    conn, client_id=client_id, folder_id=r["folder_id"]
                ),
                "output_package_id": r["output_package_id"],
                "work_order_id": r["work_order_id"],
                "created_at": r["created_at"],
            }
        )
    result: dict[str, Any] = {"match_count": len(out), "outputs": out}
    if filter_relaxed:
        result["note"] = (
            f"No artifact records work order {wo}. Artifacts filed before "
            "2026-09-05 do not carry that link, so these are the most "
            "recent outputs for this tenant instead — tell the operator "
            "they are recent files, not a confirmed match for that work "
            "order."
        )
    return result


WORKSPACE_TOOLS: dict[str, ToolDefinition] = {
    "workspace_create_folder": ToolDefinition(
        name="workspace_create_folder",
        description=(
            "Create a folder in this tenant's workspace and return its "
            "real path. Use whenever the operator asks for a folder — "
            "this performs the action; do NOT raise a work order for it "
            "and never describe a folder as created unless this tool "
            "returned one. Idempotent: naming an existing folder returns "
            "it rather than duplicating. `parent` is an existing path "
            "like 'Outputs' or 'Outputs/2026-09-05'; omit for the root."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "parent": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        handler=_create_folder,
        required_permission="workspace:write",
    ),
    "workspace_list_tree": ToolDefinition(
        name="workspace_list_tree",
        description=(
            "List this tenant's workspace folders with their real paths "
            "and file counts. Use before claiming a folder does or does "
            "not exist, and to answer 'what folders do I have?'. NEVER "
            "describe the workspace structure from memory."
        ),
        args_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=_list_tree,
        required_permission="workspace:read",
    ),
    "workspace_locate_output": ToolDefinition(
        name="workspace_locate_output",
        description=(
            "Find where produced documents were filed: filename, real "
            "folder path, artifact id and originating work order. Use "
            "for 'where is the output?', 'where did that document go?' "
            "or any request for a link to a deliverable. Optionally "
            "filter by work_order_id. Each result carries a real `url` "
            "that opens the document in the console — give the operator "
            "that url verbatim. When `url` is null the console address "
            "is not configured: say so, and give the folder_path "
            "instead. NEVER construct a workspace URL or path yourself."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "work_order_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
        handler=_locate_output,
        required_permission="workspace:read",
    ),
}
