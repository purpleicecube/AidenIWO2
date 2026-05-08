"""Pre-Beta Loop δ.2 — Workspace CRUD routes.

Operator-facing endpoints for the per-tenant workspace tree:

  GET    /workspace/tree              full folder tree + file counts
  GET    /workspace/folders/{id}      folder metadata + child folders
                                      + files inside it
  POST   /workspace/folders           create folder (parent_folder_id required)
  PATCH  /workspace/folders/{id}      rename / move (`name` and/or
                                      `parent_folder_id`)
  DELETE /workspace/folders/{id}      soft-delete; cascades to children
                                      via the soft-delete invariant
  POST   /workspace/files             create empty file (operator-typed
                                      content) OR upload via multipart
  PATCH  /workspace/files/{id}        rename / move
  DELETE /workspace/files/{id}        soft-delete (artifact stays for
                                      audit; just unlinked from folder)

Storage substrate per architect decision (B): files live in the
existing `artifacts` table joined via `workspace_folder_id`. Folders
live in the new `workspace_folders` table. RLS posture mirrors
`artifacts`.

Audit emissions (locked under PRE_BETA_PHASE_DELTA_AUDIT_EVENTS):
  folder.created / folder.renamed / folder.moved / folder.deleted
  file.created / file.renamed / file.moved / file.deleted
  file.saved_from_output                  ← emitted by tier_2_subagents,
                                             not this route module.

RBAC:
  workspace:read    → owner / admin / operator / reviewer / viewer / agent_system
  workspace:write   → owner / admin / operator / agent_system
  workspace:delete  → owner / admin
"""

from __future__ import annotations

import base64
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from authz.audit_writer import write_audit_row
from memory.canonical_facts import refresh_canonical_facts_for_tenant
from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)


router = APIRouter(prefix="/workspace", tags=["workspace"])


# ── Models ────────────────────────────────────────────────────────────


class WorkspaceFolder(BaseModel):
    id: str
    parent_folder_id: Optional[str] = None
    name: str
    created_at: str
    updated_at: str
    is_root: bool
    # Beta-1.5 phase 2 / Q11 — surface per-operator scratch ownership so
    # the UI can chip "your scratch" without a second round-trip.
    owner_user_id: Optional[str] = None


class WorkspaceFile(BaseModel):
    id: str
    workspace_folder_id: Optional[str] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    source_type: str
    content_class: str
    storage_ref: str
    created_at: str
    updated_at: str


class WorkspaceTree(BaseModel):
    folders: list[WorkspaceFolder]
    files: list[WorkspaceFile]


class FolderListResponse(BaseModel):
    folder: WorkspaceFolder
    children: list[WorkspaceFolder]
    files: list[WorkspaceFile]


class CreateFolderRequest(BaseModel):
    parent_folder_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=256)


class UpdateFolderRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    parent_folder_id: Optional[str] = None


class CreateFileRequest(BaseModel):
    workspace_folder_id: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1, max_length=512)
    mime_type: str = Field("text/plain", max_length=128)
    content_text: Optional[str] = Field(None, max_length=200_000)
    content_b64: Optional[str] = Field(None, max_length=4_000_000)


class UpdateFileRequest(BaseModel):
    filename: Optional[str] = Field(None, min_length=1, max_length=512)
    workspace_folder_id: Optional[str] = None


class FolderResponse(BaseModel):
    folder: WorkspaceFolder


class FileResponse(BaseModel):
    file: WorkspaceFile


# ── Helpers ───────────────────────────────────────────────────────────


def _folder_from_row(row: asyncpg.Record) -> WorkspaceFolder:
    # owner_user_id may be absent on rows from the tree query that
    # didn't select it; default to None.
    try:
        owner = row["owner_user_id"]
    except (KeyError, IndexError):
        owner = None
    return WorkspaceFolder(
        id=row["id"],
        parent_folder_id=row["parent_folder_id"],
        name=row["name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        is_root=row["parent_folder_id"] is None,
        owner_user_id=owner,
    )


def _file_from_row(row: asyncpg.Record) -> WorkspaceFile:
    return WorkspaceFile(
        id=row["id"],
        workspace_folder_id=row["workspace_folder_id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        source_type=row["source_type"],
        content_class=row["content_class"],
        storage_ref=row["storage_ref"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _ensure_folder_exists(
    conn: asyncpg.Connection, folder_id: str
) -> asyncpg.Record:
    try:
        row = await conn.fetchrow(
            """
            SELECT id::text             AS id,
                   parent_folder_id::text AS parent_folder_id,
                   name,
                   client_id::text     AS client_id,
                   owner_user_id::text AS owner_user_id,
                   created_at::text    AS created_at,
                   updated_at::text    AS updated_at
              FROM workspace_folders
             WHERE id = $1::uuid AND deleted_at IS NULL
            """,
            folder_id,
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_folder_id", "value": folder_id},
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "folder_not_found", "id": folder_id},
        )
    return row


async def _ensure_file_exists(
    conn: asyncpg.Connection, file_id: str
) -> asyncpg.Record:
    try:
        row = await conn.fetchrow(
            """
            SELECT id::text                AS id,
                   workspace_folder_id::text AS workspace_folder_id,
                   filename,
                   mime_type,
                   source_type::text       AS source_type,
                   content_class::text     AS content_class,
                   storage_ref,
                   created_at::text        AS created_at,
                   updated_at::text        AS updated_at
              FROM artifacts
             WHERE id = $1::uuid
            """,
            file_id,
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_file_id", "value": file_id},
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "file_not_found", "id": file_id},
        )
    return row


async def _detect_cycle(
    conn: asyncpg.Connection,
    *,
    folder_id: str,
    new_parent_id: str,
) -> bool:
    """Return True if making new_parent_id the parent of folder_id would
    create a cycle (i.e. new_parent_id is folder_id itself or one of its
    descendants)."""
    if folder_id == new_parent_id:
        return True
    cur = new_parent_id
    for _ in range(64):  # reasonable depth ceiling
        row = await conn.fetchrow(
            """
            SELECT parent_folder_id::text AS parent_folder_id
              FROM workspace_folders
             WHERE id = $1::uuid AND deleted_at IS NULL
            """,
            cur,
        )
        if row is None:
            return False
        if row["parent_folder_id"] is None:
            return False
        if row["parent_folder_id"] == folder_id:
            return True
        cur = row["parent_folder_id"]
    return True  # pathological depth → reject


# ── Tree + folder reads ──────────────────────────────────────────────


@router.get(
    "/tree",
    response_model=WorkspaceTree,
    dependencies=[Depends(require_permission_dep("workspace:read"))],
)
async def get_workspace_tree(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> WorkspaceTree:
    # Beta-1.5 ε.5 / Q11 architect-flagged fix:
    # Per-operator scratch folders (owner_user_id IS NOT NULL) must be
    # visible only to their owner. Tenant-shared folders (owner_user_id
    # IS NULL) remain visible to every tenant member with workspace:read.
    folder_rows = await conn.fetch(
        """
        SELECT id::text             AS id,
               parent_folder_id::text AS parent_folder_id,
               name,
               owner_user_id::text AS owner_user_id,
               created_at::text    AS created_at,
               updated_at::text    AS updated_at
          FROM workspace_folders
         WHERE deleted_at IS NULL
           AND (owner_user_id IS NULL OR owner_user_id = $1::uuid)
         ORDER BY (parent_folder_id IS NOT NULL),  -- root first
                  parent_folder_id NULLS FIRST,
                  name
        """,
        ctx["user_id"],
    )
    # Files inherit visibility from their containing folder. EXISTS
    # subquery is RLS-tenant-scoped via the same connection, so we
    # only need to additionally enforce the per-operator filter on
    # the parent folder.
    file_rows = await conn.fetch(
        """
        SELECT a.id::text                AS id,
               a.workspace_folder_id::text AS workspace_folder_id,
               a.filename,
               a.mime_type,
               a.source_type::text       AS source_type,
               a.content_class::text     AS content_class,
               a.storage_ref,
               a.created_at::text        AS created_at,
               a.updated_at::text        AS updated_at
          FROM artifacts a
          JOIN workspace_folders wf ON wf.id = a.workspace_folder_id
         WHERE a.workspace_folder_id IS NOT NULL
           AND wf.deleted_at IS NULL
           AND (wf.owner_user_id IS NULL OR wf.owner_user_id = $1::uuid)
         ORDER BY a.filename
        """,
        ctx["user_id"],
    )
    return WorkspaceTree(
        folders=[_folder_from_row(r) for r in folder_rows],
        files=[_file_from_row(r) for r in file_rows],
    )


@router.get(
    "/folders/{folder_id}",
    response_model=FolderListResponse,
    dependencies=[Depends(require_permission_dep("workspace:read"))],
)
async def get_folder_contents(
    folder_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> FolderListResponse:
    folder = await _ensure_folder_exists(conn, folder_id)
    # Beta-1.5 ε.5 / Q11 — block other operators from listing
    # someone else's per-operator scratch folder by id, and filter
    # children + files by the same predicate.
    if (
        folder["owner_user_id"]
        and folder["owner_user_id"] != ctx["user_id"]
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "folder_not_found", "id": folder_id},
        )
    children = await conn.fetch(
        """
        SELECT id::text             AS id,
               parent_folder_id::text AS parent_folder_id,
               name,
               created_at::text    AS created_at,
               updated_at::text    AS updated_at
          FROM workspace_folders
         WHERE parent_folder_id = $1::uuid AND deleted_at IS NULL
           AND (owner_user_id IS NULL OR owner_user_id = $2::uuid)
         ORDER BY name
        """,
        folder_id,
        ctx["user_id"],
    )
    files = await conn.fetch(
        """
        SELECT a.id::text                AS id,
               a.workspace_folder_id::text AS workspace_folder_id,
               a.filename,
               a.mime_type,
               a.source_type::text       AS source_type,
               a.content_class::text     AS content_class,
               a.storage_ref,
               a.created_at::text        AS created_at,
               a.updated_at::text        AS updated_at
          FROM artifacts a
          JOIN workspace_folders wf ON wf.id = a.workspace_folder_id
         WHERE a.workspace_folder_id = $1::uuid
           AND wf.deleted_at IS NULL
           AND (wf.owner_user_id IS NULL OR wf.owner_user_id = $2::uuid)
         ORDER BY a.filename
        """,
        folder_id,
        ctx["user_id"],
    )
    return FolderListResponse(
        folder=_folder_from_row(folder),
        children=[_folder_from_row(r) for r in children],
        files=[_file_from_row(r) for r in files],
    )


# ── Folder mutations ─────────────────────────────────────────────────


@router.post(
    "/folders/scratch",
    response_model=FolderResponse,
    dependencies=[Depends(require_permission_dep("workspace:write"))],
)
async def create_or_get_scratch_folder(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> FolderResponse:
    """Beta-1.5 phase 2 / Q11 — idempotent per-operator scratch folder.

    The first call materialises a folder under the tenant root with
    ``owner_user_id = ctx.user_id`` and a stable name (`Scratch (you)`).
    Subsequent calls return the existing row. Foreign-scratch
    visibility is already filtered server-side by the tree query.
    """
    root = await conn.fetchrow(
        """
        SELECT id::text AS id
          FROM workspace_folders
         WHERE deleted_at IS NULL
           AND parent_folder_id IS NULL
           AND owner_user_id IS NULL
         LIMIT 1
        """
    )
    if root is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "tenant_workspace_root_missing"},
        )

    existing = await conn.fetchrow(
        """
        SELECT id::text             AS id,
               parent_folder_id::text AS parent_folder_id,
               name,
               owner_user_id::text AS owner_user_id,
               deleted_at,
               created_at::text    AS created_at,
               updated_at::text    AS updated_at
          FROM workspace_folders
         WHERE owner_user_id = $1::uuid
           AND parent_folder_id = $2::uuid
         ORDER BY created_at
         LIMIT 1
        """,
        ctx["user_id"],
        root["id"],
    )
    if existing is not None and existing["deleted_at"] is None:
        return FolderResponse(folder=_folder_from_row(existing))
    if existing is not None and existing["deleted_at"] is not None:
        # Soft-deleted scratch exists; restore it. Preserves any prior
        # contents (subfolders, files) the operator left behind, and
        # avoids the (client_id, parent_folder_id, name) UNIQUE
        # collision that a fresh INSERT would trigger.
        # lint:bypass-rls-explain="workspace_folders is RLS-FORCED on tenant-scoped connection."
        row = await conn.fetchrow(
            """
            UPDATE workspace_folders
               SET deleted_at = NULL, updated_at = now()
             WHERE id = $1::uuid
            RETURNING id::text             AS id,
                      parent_folder_id::text AS parent_folder_id,
                      name,
                      owner_user_id::text AS owner_user_id,
                      created_at::text    AS created_at,
                      updated_at::text    AS updated_at
            """,
            existing["id"],
        )
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="folder.created",
            target_type="workspace_folder",
            target_id=row["id"],
            metadata={
                "name": row["name"],
                "parentFolderId": root["id"],
                "ownerUserId": ctx["user_id"],
                "scope": "per_operator_scratch",
                "restoredFromSoftDelete": True,
            },
        )
        return FolderResponse(folder=_folder_from_row(row))

    row = await conn.fetchrow(
        """
        INSERT INTO workspace_folders
          (client_id, parent_folder_id, name, owner_user_id,
           created_by_user_id)
        VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $4::uuid)
        RETURNING id::text             AS id,
                  parent_folder_id::text AS parent_folder_id,
                  name,
                  owner_user_id::text AS owner_user_id,
                  created_at::text    AS created_at,
                  updated_at::text    AS updated_at
        """,
        ctx["client_id"],
        root["id"],
        "Scratch (you)",
        ctx["user_id"],
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="folder.created",
        target_type="workspace_folder",
        target_id=row["id"],
        metadata={
            "name": row["name"],
            "parentFolderId": root["id"],
            "ownerUserId": ctx["user_id"],
            "scope": "per_operator_scratch",
        },
    )
    return FolderResponse(folder=_folder_from_row(row))


@router.post(
    "/folders",
    response_model=FolderResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission_dep("workspace:write"))],
)
async def create_folder(
    body: CreateFolderRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> FolderResponse:
    parent = await _ensure_folder_exists(conn, body.parent_folder_id)
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO workspace_folders
              (client_id, parent_folder_id, name, created_by_user_id)
            VALUES ($1::uuid, $2::uuid, $3, $4::uuid)
            RETURNING id::text             AS id,
                      parent_folder_id::text AS parent_folder_id,
                      name,
                      created_at::text    AS created_at,
                      updated_at::text    AS updated_at
            """,
            ctx["client_id"],
            body.parent_folder_id,
            body.name,
            ctx["user_id"],
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "folder_name_conflict",
                "parent_folder_id": body.parent_folder_id,
                "name": body.name,
            },
        )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="folder.created",
        target_type="workspace_folder",
        target_id=row["id"],
        metadata={
            "name": body.name,
            "parentFolderId": body.parent_folder_id,
        },
    )
    # Loop Iota — a new folder named "Canonical Facts" creates an empty
    # canonical-facts source. The hook runs unconditionally; cheap when
    # no match.
    await refresh_canonical_facts_for_tenant(conn, client_id=ctx["client_id"])
    return FolderResponse(folder=_folder_from_row(row))


@router.patch(
    "/folders/{folder_id}",
    response_model=FolderResponse,
    dependencies=[Depends(require_permission_dep("workspace:write"))],
)
async def update_folder(
    folder_id: str,
    body: UpdateFolderRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> FolderResponse:
    folder = await _ensure_folder_exists(conn, folder_id)
    if folder["parent_folder_id"] is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "cannot_modify_tenant_root"},
        )

    sets: list[str] = []
    args: list[Any] = []
    event = "folder.renamed"
    metadata: dict[str, Any] = {"folderId": folder_id}

    if body.name is not None and body.name != folder["name"]:
        args.append(body.name)
        sets.append(f"name = ${len(args)}")
        metadata["oldName"] = folder["name"]
        metadata["newName"] = body.name
    if (
        body.parent_folder_id is not None
        and body.parent_folder_id != folder["parent_folder_id"]
    ):
        # Validate target parent + cycle.
        await _ensure_folder_exists(conn, body.parent_folder_id)
        if await _detect_cycle(
            conn,
            folder_id=folder_id,
            new_parent_id=body.parent_folder_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "move_would_create_cycle"},
            )
        args.append(body.parent_folder_id)
        sets.append(f"parent_folder_id = ${len(args)}::uuid")
        metadata["oldParentFolderId"] = folder["parent_folder_id"]
        metadata["newParentFolderId"] = body.parent_folder_id
        event = "folder.moved"

    if not sets:
        return FolderResponse(folder=_folder_from_row(folder))

    sets.append("updated_at = now()")
    args.append(folder_id)

    # lint:bypass-rls-explain="workspace_folders is RLS-FORCED (migration 0014); route runs on tenant-scoped connection so cross-tenant ids are invisible. WHERE id alone is safe."
    sql = f"""
        UPDATE workspace_folders
           SET {', '.join(sets)}
         WHERE id = ${len(args)}::uuid AND deleted_at IS NULL
        RETURNING id::text             AS id,
                  parent_folder_id::text AS parent_folder_id,
                  name,
                  created_at::text    AS created_at,
                  updated_at::text    AS updated_at
    """
    try:
        row = await conn.fetchrow(sql, *args)
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "folder_name_conflict"},
        )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event=event,
        target_type="workspace_folder",
        target_id=row["id"],
        metadata=metadata,
    )
    # Loop Iota — folder rename/move can flip a folder in/out of the
    # Canonical Facts subtree.
    await refresh_canonical_facts_for_tenant(conn, client_id=ctx["client_id"])
    return FolderResponse(folder=_folder_from_row(row))


@router.delete(
    "/folders/{folder_id}",
    response_model=FolderResponse,
    dependencies=[Depends(require_permission_dep("workspace:delete"))],
)
async def delete_folder(
    folder_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    hard: bool = False,
) -> FolderResponse:
    """Soft delete (default) or hard delete (?hard=true) per Beta-1 Q10
    architect lock. Hard delete cascades through children (DB
    constraints enforce restrict on parent FK; we do a recursive sweep
    inside the tx so parent rows can disappear after their children).
    """
    folder = await _ensure_folder_exists(conn, folder_id)
    if folder["parent_folder_id"] is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "cannot_delete_tenant_root"},
        )

    if hard:
        # Recursively collect descendant folder ids WITH depth so we
        # can delete leaves first (FK on parent_folder_id is RESTRICT).
        # Python-side sort is portable and explicit.
        descendants = await conn.fetch(
            """
            WITH RECURSIVE descendants AS (
              SELECT id, 0 AS depth
                FROM workspace_folders
               WHERE id = $1::uuid
              UNION ALL
              SELECT wf.id, d.depth + 1
                FROM workspace_folders wf
                JOIN descendants d ON wf.parent_folder_id = d.id
            )
            SELECT id::text AS id, depth FROM descendants
            """,
            folder_id,
        )
        # Deepest-first so leaves disappear before their parents.
        sorted_ids = [
            d["id"]
            for d in sorted(descendants, key=lambda r: -r["depth"])
        ]
        # lint:bypass-rls-explain="workspace_folders + artifacts are both RLS-FORCED on the tenant-scoped connection"
        await conn.execute(
            "UPDATE artifacts SET workspace_folder_id = NULL "
            "WHERE workspace_folder_id::text = ANY($1::text[])",
            sorted_ids,
        )
        # lint:bypass-rls-explain="leaves-first DELETE sequence avoids FK RESTRICT; RLS scopes row visibility"
        for fid in sorted_ids:
            await conn.execute(
                "DELETE FROM workspace_folders WHERE id = $1::uuid",
                fid,
            )
        # Return a synthetic row so the caller sees what was deleted.
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="folder.deleted",
            target_type="workspace_folder",
            target_id=folder_id,
            metadata={
                "name": folder["name"],
                "hardDelete": True,
                "cascadeCount": len(sorted_ids),
            },
        )
        # Loop Iota — hard delete may have removed a Canonical Facts
        # subtree. Refresh.
        await refresh_canonical_facts_for_tenant(
            conn, client_id=ctx["client_id"]
        )
        return FolderResponse(folder=WorkspaceFolder(
            id=folder_id,
            parent_folder_id=folder["parent_folder_id"],
            name=folder["name"],
            created_at=folder["created_at"],
            updated_at=folder["updated_at"],
            is_root=False,
        ))

    # Soft delete (default): mark deleted_at, leave the row intact.
    # lint:bypass-rls-explain="workspace_folders is RLS-FORCED; route runs on tenant-scoped connection. WHERE id is safe."
    row = await conn.fetchrow(
        """
        UPDATE workspace_folders
           SET deleted_at = now(), updated_at = now()
         WHERE id = $1::uuid AND deleted_at IS NULL
        RETURNING id::text             AS id,
                  parent_folder_id::text AS parent_folder_id,
                  name,
                  created_at::text    AS created_at,
                  updated_at::text    AS updated_at
        """,
        folder_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "folder_not_found_or_already_deleted"},
        )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="folder.deleted",
        target_type="workspace_folder",
        target_id=row["id"],
        metadata={"name": row["name"], "hardDelete": False},
    )
    # Loop Iota — soft delete may hide a Canonical Facts folder; the
    # refresh helper filters on `deleted_at IS NULL`, so the next
    # rebuild excludes it.
    await refresh_canonical_facts_for_tenant(conn, client_id=ctx["client_id"])
    return FolderResponse(folder=_folder_from_row(row))


# ── File mutations ───────────────────────────────────────────────────


@router.post(
    "/files",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission_dep("workspace:write"))],
)
async def create_file(
    body: CreateFileRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> FileResponse:
    """Create a workspace file. Either `content_text` (utf-8 plaintext)
    or `content_b64` (base64-encoded binary) — empty file allowed."""
    await _ensure_folder_exists(conn, body.workspace_folder_id)

    # Resolve storage. Two paths:
    #   - content_text → store inline in `extracted_text`; storage_ref
    #     becomes a sentinel URI ("inline://<uuid>" decoded later).
    #   - content_b64  → decode + store inline as a base64 string
    #     prefixed with "b64:". Filesystem storage is Beta scope.
    extracted_text: Optional[str] = None
    storage_ref = "inline://workspace"
    if body.content_text is not None:
        extracted_text = body.content_text
    elif body.content_b64:
        try:
            base64.b64decode(body.content_b64, validate=True)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_content_b64"},
            )
        # We don't decode-and-re-encode — just keep the original.
        extracted_text = "b64:" + body.content_b64

    row = await conn.fetchrow(
        """
        INSERT INTO artifacts
          (client_id, source_type, content_class, mime_type, filename,
           storage_ref, extracted_text, workspace_folder_id,
           created_by_user_id)
        VALUES ($1::uuid, 'upload'::artifact_source_type,
                'c1'::artifact_content_class, $2, $3, $4, $5,
                $6::uuid, $7::uuid)
        RETURNING id::text                AS id,
                  workspace_folder_id::text AS workspace_folder_id,
                  filename,
                  mime_type,
                  source_type::text       AS source_type,
                  content_class::text     AS content_class,
                  storage_ref,
                  created_at::text        AS created_at,
                  updated_at::text        AS updated_at
        """,
        ctx["client_id"],
        body.mime_type,
        body.filename,
        storage_ref,
        extracted_text,
        body.workspace_folder_id,
        ctx["user_id"],
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="file.created",
        target_type="artifact",
        target_id=row["id"],
        metadata={
            "filename": body.filename,
            "mimeType": body.mime_type,
            "workspaceFolderId": body.workspace_folder_id,
        },
    )
    # Loop Iota — refresh canonical facts blob if this write affects
    # the tenant's `Canonical Facts/` subtree. No-op when no such
    # folder exists.
    await refresh_canonical_facts_for_tenant(conn, client_id=ctx["client_id"])
    return FileResponse(file=_file_from_row(row))


@router.patch(
    "/files/{file_id}",
    response_model=FileResponse,
    dependencies=[Depends(require_permission_dep("workspace:write"))],
)
async def update_file(
    file_id: str,
    body: UpdateFileRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> FileResponse:
    f = await _ensure_file_exists(conn, file_id)
    sets: list[str] = []
    args: list[Any] = []
    event = "file.renamed"
    metadata: dict[str, Any] = {"fileId": file_id}

    if body.filename is not None and body.filename != f["filename"]:
        args.append(body.filename)
        sets.append(f"filename = ${len(args)}")
        metadata["oldFilename"] = f["filename"]
        metadata["newFilename"] = body.filename
    if (
        body.workspace_folder_id is not None
        and body.workspace_folder_id != f["workspace_folder_id"]
    ):
        await _ensure_folder_exists(conn, body.workspace_folder_id)
        args.append(body.workspace_folder_id)
        sets.append(f"workspace_folder_id = ${len(args)}::uuid")
        metadata["oldFolderId"] = f["workspace_folder_id"]
        metadata["newFolderId"] = body.workspace_folder_id
        event = "file.moved"

    if not sets:
        return FileResponse(file=_file_from_row(f))

    sets.append("updated_at = now()")
    args.append(file_id)
    # lint:bypass-rls-explain="artifacts is RLS-FORCED (migration 0006); the route runs on get_tenant_scoped_connection so cross-tenant artifact ids are invisible at row-visibility level. WHERE id alone is sufficient because RLS rejects out-of-tenant rows before UPDATE fires."
    sql = f"""
        UPDATE artifacts
           SET {', '.join(sets)}
         WHERE id = ${len(args)}::uuid
        RETURNING id::text                AS id,
                  workspace_folder_id::text AS workspace_folder_id,
                  filename,
                  mime_type,
                  source_type::text       AS source_type,
                  content_class::text     AS content_class,
                  storage_ref,
                  created_at::text        AS created_at,
                  updated_at::text        AS updated_at
    """
    row = await conn.fetchrow(sql, *args)
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event=event,
        target_type="artifact",
        target_id=row["id"],
        metadata=metadata,
    )
    # Loop Iota — file rename / move may pull a file in or out of the
    # Canonical Facts subtree. Refresh on both paths.
    await refresh_canonical_facts_for_tenant(conn, client_id=ctx["client_id"])
    return FileResponse(file=_file_from_row(row))


@router.delete(
    "/files/{file_id}",
    response_model=FileResponse,
    dependencies=[Depends(require_permission_dep("workspace:delete"))],
)
async def delete_file(
    file_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    hard: bool = False,
) -> FileResponse:
    """Soft-delete (default): unlink from workspace tree (set
    workspace_folder_id to NULL) — artifact row stays for audit.
    Hard-delete (?hard=true): drop the artifact row entirely
    (Beta-1 Q10 lock; admin-explicit via workspace:delete RBAC)."""
    f = await _ensure_file_exists(conn, file_id)
    if hard:
        # lint:bypass-rls-explain="artifacts is RLS-FORCED; route runs on tenant-scoped connection."
        await conn.execute(
            "DELETE FROM artifacts WHERE id = $1::uuid",
            file_id,
        )
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="file.deleted",
            target_type="artifact",
            target_id=file_id,
            metadata={
                "filename": f["filename"],
                "previousFolderId": f["workspace_folder_id"],
                "hardDelete": True,
            },
        )
        # Loop Iota — hard delete may remove a Canonical Facts file.
        await refresh_canonical_facts_for_tenant(
            conn, client_id=ctx["client_id"]
        )
        return FileResponse(file=_file_from_row(f))

    # Soft delete: unlink from folder tree.
    # lint:bypass-rls-explain="artifacts is RLS-FORCED; route runs on tenant-scoped connection. WHERE id alone is safe because RLS rejects out-of-tenant ids."
    row = await conn.fetchrow(
        """
        UPDATE artifacts
           SET workspace_folder_id = NULL, updated_at = now()
         WHERE id = $1::uuid
        RETURNING id::text                AS id,
                  workspace_folder_id::text AS workspace_folder_id,
                  filename,
                  mime_type,
                  source_type::text       AS source_type,
                  content_class::text     AS content_class,
                  storage_ref,
                  created_at::text        AS created_at,
                  updated_at::text        AS updated_at
        """,
        file_id,
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="file.deleted",
        target_type="artifact",
        target_id=row["id"],
        metadata={
            "filename": f["filename"],
            "previousFolderId": f["workspace_folder_id"],
            "hardDelete": False,
        },
    )
    # Loop Iota — soft delete unlinks the file from the workspace tree.
    # Refresh in case the unlinked file was part of Canonical Facts.
    await refresh_canonical_facts_for_tenant(conn, client_id=ctx["client_id"])
    return FileResponse(file=_file_from_row(row))


# ── Q9: workspace file content fetch ──────────────────────────────────


class FileContentResponse(BaseModel):
    id: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    encoding: str  # "utf-8" | "base64" | "ref"
    content: Optional[str] = None
    storage_ref: Optional[str] = None
    truncated: bool = False
    size_bytes: int = 0


_INLINE_TEXT_MIMES = {
    "text/plain", "text/markdown", "text/csv", "text/html",
    "application/json", "application/xml",
}
_INLINE_IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_MAX_INLINE_CHARS = 200_000   # ~200 KB
_MAX_BASE64_CHARS = 4_000_000  # ~4 MB after decode


@router.get(
    "/files/{file_id}/content",
    response_model=FileContentResponse,
    dependencies=[Depends(require_permission_dep("workspace:read"))],
)
async def get_file_content(
    file_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> FileContentResponse:
    """Beta-1 Q9 — return file content in JSON.
       text mimes  → utf-8 inline string (capped at 200 KB)
       image mimes → base64 string (capped at ~4 MB after encode)
       output_package://... → 'ref' encoding; client uses Output Packages
       anything larger → truncated=true with size hint
    """
    try:
        row = await conn.fetchrow(
            """
            SELECT id::text                AS id,
                   filename,
                   mime_type,
                   storage_ref,
                   extracted_text
              FROM artifacts
             WHERE id = $1::uuid
            """,
            file_id,
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_file_id", "value": file_id},
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "file_not_found", "id": file_id},
        )

    storage_ref = row["storage_ref"] or ""
    mime = row["mime_type"] or "application/octet-stream"
    extracted = row["extracted_text"] or ""

    # output_package:// → ref-only response. Client deep-links via the
    # Output Packages surface, which has the full deliverable + handoff
    # state. Returning the markdown here would diverge from the
    # canonical output package source over time.
    if storage_ref.startswith("output_package://"):
        return FileContentResponse(
            id=row["id"],
            filename=row["filename"],
            mime_type=mime,
            encoding="ref",
            storage_ref=storage_ref,
            content=None,
            size_bytes=len(extracted),
        )

    # Inline-stored text/markdown/json/csv — return as utf-8 string.
    if mime in _INLINE_TEXT_MIMES or mime.startswith("text/"):
        truncated = len(extracted) > _MAX_INLINE_CHARS
        body = extracted[:_MAX_INLINE_CHARS] if truncated else extracted
        return FileContentResponse(
            id=row["id"],
            filename=row["filename"],
            mime_type=mime,
            encoding="utf-8",
            content=body,
            truncated=truncated,
            size_bytes=len(extracted),
        )

    # Inline-stored binary (we wrote with the "b64:" prefix on upload).
    if extracted.startswith("b64:"):
        b64_body = extracted[4:]
        truncated = len(b64_body) > _MAX_BASE64_CHARS
        body = b64_body[:_MAX_BASE64_CHARS] if truncated else b64_body
        return FileContentResponse(
            id=row["id"],
            filename=row["filename"],
            mime_type=mime,
            encoding="base64",
            content=body,
            truncated=truncated,
            size_bytes=len(b64_body),
        )

    # Fallback: ref-only (rare path; should only fire for legacy rows).
    return FileContentResponse(
        id=row["id"],
        filename=row["filename"],
        mime_type=mime,
        encoding="ref",
        storage_ref=storage_ref,
        content=None,
        size_bytes=len(extracted),
    )
