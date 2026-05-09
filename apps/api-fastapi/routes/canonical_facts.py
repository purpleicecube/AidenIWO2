"""Loop Kappa — Memory V1.5 canonical facts CRUD route.

Operator-facing endpoints for the per-tenant `canonical_facts` table:

  GET    /canonical_facts            list all rows (active + inactive)
                                     for the active tenant
  POST   /canonical_facts            create a new fact
  PATCH  /canonical_facts/{id}       update body / severity / activation
  DELETE /canonical_facts/{id}       soft-delete (is_active=false)

Every mutation triggers `refresh_canonical_facts_from_table()` which
rebuilds `clients.canonical_facts_blob` and bumps
`canonical_facts_revision`. The next chat turn picks up the change
automatically via the Memory V1 builder.

RBAC:
  - canonical_facts:read         owner / admin / operator / reviewer / viewer / agent_system
  - canonical_facts:create       owner / admin / operator
  - canonical_facts:update       owner / admin / operator
  - canonical_facts:delete       owner / admin
  - canonical_facts:set_severity owner / admin
                                 (operator's PATCH cannot change
                                  severity without this permission)

Audit (LOOP_KAPPA_AUDIT_EVENTS):
  - canonical_facts.created
  - canonical_facts.updated
  - canonical_facts.deleted

Tenant safety: every query carries explicit `client_id = $1`. RLS +
FORCE on `canonical_facts` is the hard wall. ADR-014 §Q4 keep_both
posture preserved.
"""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from authz.audit_writer import write_audit_row
from authz.check_permission import check_permission_decide
from deps import (
    _load_permission_ctx,
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)
from memory.canonical_facts_service import refresh_canonical_facts_from_table


router = APIRouter(prefix="/canonical_facts", tags=["canonical_facts"])


_VALID_SEVERITIES = {"critical", "high", "medium", "low"}


# ── Models ────────────────────────────────────────────────────────────


class CanonicalFactRow(BaseModel):
    id: str
    client_id: str
    severity: str
    version: int
    authored_by_user_id: Optional[str] = None
    body: str
    is_active: bool
    created_at: str
    updated_at: str


class CanonicalFactList(BaseModel):
    rows: list[CanonicalFactRow]
    blob_revision: int


class CreateCanonicalFactRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=20_000)
    severity: str = Field("medium", min_length=1)


class UpdateCanonicalFactRequest(BaseModel):
    body: Optional[str] = Field(None, min_length=1, max_length=20_000)
    severity: Optional[str] = Field(None, min_length=1)
    is_active: Optional[bool] = None


class CanonicalFactResponse(BaseModel):
    fact: CanonicalFactRow
    blob_revision: int


# ── Helpers ───────────────────────────────────────────────────────────


def _row_to_model(row: asyncpg.Record) -> CanonicalFactRow:
    return CanonicalFactRow(
        id=row["id"],
        client_id=row["client_id"],
        severity=row["severity"],
        version=int(row["version"] or 1),
        authored_by_user_id=row.get("authored_by_user_id"),
        body=row["body"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _fetch_fact(
    conn: asyncpg.Connection, *, fact_id: str
) -> asyncpg.Record:
    try:
        row = await conn.fetchrow(
            """
            SELECT id::text                  AS id,
                   client_id::text           AS client_id,
                   severity                  AS severity,
                   version                   AS version,
                   authored_by_user_id::text AS authored_by_user_id,
                   body                      AS body,
                   is_active                 AS is_active,
                   created_at::text          AS created_at,
                   updated_at::text          AS updated_at
            FROM canonical_facts
            WHERE id = $1::uuid
            """,
            fact_id,
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_fact_id", "value": fact_id},
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "canonical_fact_not_found", "id": fact_id},
        )
    return row


async def _current_revision(
    conn: asyncpg.Connection, *, client_id: str
) -> int:
    row = await conn.fetchrow(
        """
        SELECT canonical_facts_revision::int AS rev
        FROM clients
        WHERE id = $1::uuid
        """,
        client_id,
    )
    return int(row["rev"]) if row else 0


# ── Routes ────────────────────────────────────────────────────────────


@router.get("", response_model=CanonicalFactList)
async def list_canonical_facts(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    _: Annotated[None, Depends(require_permission_dep("canonical_facts:read"))],
    include_inactive: bool = False,
) -> CanonicalFactList:
    """List every canonical fact row for the active tenant.

    Default returns only `is_active = true`. Pass `include_inactive=true`
    to see soft-deleted rows for audit/restore workflows.
    """
    sql = """
        SELECT id::text                  AS id,
               client_id::text           AS client_id,
               severity                  AS severity,
               version                   AS version,
               authored_by_user_id::text AS authored_by_user_id,
               body                      AS body,
               is_active                 AS is_active,
               created_at::text          AS created_at,
               updated_at::text          AS updated_at
        FROM canonical_facts
        WHERE client_id = $1::uuid
    """
    if not include_inactive:
        sql += " AND is_active = true"
    sql += """
        ORDER BY
            CASE severity
                WHEN 'critical' THEN 0
                WHEN 'high'     THEN 1
                WHEN 'medium'   THEN 2
                WHEN 'low'      THEN 3
                ELSE 99
            END,
            version DESC,
            created_at ASC
    """
    rows = await conn.fetch(sql, ctx["client_id"])
    return CanonicalFactList(
        rows=[_row_to_model(r) for r in rows],
        blob_revision=await _current_revision(conn, client_id=ctx["client_id"]),
    )


@router.post("", response_model=CanonicalFactResponse, status_code=status.HTTP_201_CREATED)
async def create_canonical_fact(
    body: CreateCanonicalFactRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    _: Annotated[None, Depends(require_permission_dep("canonical_facts:create"))],
) -> CanonicalFactResponse:
    """Create a new canonical fact. Triggers blob refresh +
    `canonical_facts_revision` bump.
    """
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_severity",
                "value": body.severity,
                "allowed": sorted(_VALID_SEVERITIES),
            },
        )
    row = await conn.fetchrow(
        """
        INSERT INTO canonical_facts
            (client_id, severity, version, authored_by_user_id, body, is_active)
        VALUES
            ($1::uuid, $2, 1, $3::uuid, $4, true)
        RETURNING id::text                  AS id,
                  client_id::text           AS client_id,
                  severity                  AS severity,
                  version                   AS version,
                  authored_by_user_id::text AS authored_by_user_id,
                  body                      AS body,
                  is_active                 AS is_active,
                  created_at::text          AS created_at,
                  updated_at::text          AS updated_at
        """,
        ctx["client_id"],
        body.severity,
        ctx["user_id"],
        body.body,
    )
    new_rev = await refresh_canonical_facts_from_table(
        conn, client_id=ctx["client_id"]
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="canonical_facts.created",
        target_type="canonical_fact",
        target_id=row["id"],
        metadata={
            "fact_id": row["id"],
            "severity": row["severity"],
            "version": int(row["version"] or 1),
            "body_length": len(row["body"] or ""),
            "blob_revision": new_rev,
        },
    )
    return CanonicalFactResponse(
        fact=_row_to_model(row),
        blob_revision=new_rev or 0,
    )


@router.patch("/{fact_id}", response_model=CanonicalFactResponse)
async def update_canonical_fact(
    fact_id: str,
    body: UpdateCanonicalFactRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    _: Annotated[None, Depends(require_permission_dep("canonical_facts:update"))],
) -> CanonicalFactResponse:
    """Update body / severity / activation on an existing fact.

    Severity changes require the additional `canonical_facts:set_severity`
    permission. Body and `is_active` updates only need
    `canonical_facts:update` (already gated above).
    """
    existing = await _fetch_fact(conn, fact_id=fact_id)

    fields_changed: list[str] = []
    new_body = existing["body"]
    new_severity = existing["severity"]
    new_is_active = existing["is_active"]

    if body.body is not None and body.body != existing["body"]:
        new_body = body.body
        fields_changed.append("body")
    if body.is_active is not None and body.is_active != existing["is_active"]:
        new_is_active = body.is_active
        fields_changed.append("is_active")
    if body.severity is not None and body.severity != existing["severity"]:
        if body.severity not in _VALID_SEVERITIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_severity",
                    "value": body.severity,
                    "allowed": sorted(_VALID_SEVERITIES),
                },
            )
        # Severity changes require the additional set_severity
        # permission. Operator role has :update but not :set_severity
        # — so the severity field of a PATCH from an operator gets
        # rejected even though the rest of the body is allowed.
        perm_inputs = await _load_permission_ctx(
            conn,
            ctx["user_id"],
            ctx["client_id"],
            "canonical_facts:set_severity",
        )
        decision = check_permission_decide(
            role=perm_inputs["role"],
            role_permissions=perm_inputs["role_permissions"],
            user_grants=perm_inputs["user_grants"],
            permission="canonical_facts:set_severity",
            known_permissions=perm_inputs.get("known_permissions"),
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "permission_denied",
                    "permission": "canonical_facts:set_severity",
                    "reason": decision.reason,
                },
            )
        new_severity = body.severity
        fields_changed.append("severity")

    if not fields_changed:
        return CanonicalFactResponse(
            fact=_row_to_model(existing),
            blob_revision=await _current_revision(
                conn, client_id=ctx["client_id"]
            ),
        )

    new_version = int(existing["version"] or 1) + 1
    row = await conn.fetchrow(
        """
        UPDATE canonical_facts
        SET body       = $2,
            severity   = $3,
            is_active  = $4,
            version    = $5,
            updated_at = now()
        WHERE id = $1::uuid
        RETURNING id::text                  AS id,
                  client_id::text           AS client_id,
                  severity                  AS severity,
                  version                   AS version,
                  authored_by_user_id::text AS authored_by_user_id,
                  body                      AS body,
                  is_active                 AS is_active,
                  created_at::text          AS created_at,
                  updated_at::text          AS updated_at
        """,
        fact_id,
        new_body,
        new_severity,
        new_is_active,
        new_version,
    )
    new_rev = await refresh_canonical_facts_from_table(
        conn, client_id=ctx["client_id"]
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="canonical_facts.updated",
        target_type="canonical_fact",
        target_id=row["id"],
        metadata={
            "fact_id": row["id"],
            "fields_changed": fields_changed,
            "previous_version": int(existing["version"] or 1),
            "new_version": new_version,
            "blob_revision": new_rev,
        },
    )
    return CanonicalFactResponse(
        fact=_row_to_model(row),
        blob_revision=new_rev or 0,
    )


@router.delete("/{fact_id}", response_model=CanonicalFactResponse)
async def delete_canonical_fact(
    fact_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    _: Annotated[None, Depends(require_permission_dep("canonical_facts:delete"))],
) -> CanonicalFactResponse:
    """Soft-delete: set `is_active=false`. Preserves audit lineage.
    Triggers blob refresh.
    """
    existing = await _fetch_fact(conn, fact_id=fact_id)

    if not existing["is_active"]:
        # Already inactive — return current state without bumping revision.
        return CanonicalFactResponse(
            fact=_row_to_model(existing),
            blob_revision=await _current_revision(
                conn, client_id=ctx["client_id"]
            ),
        )

    row = await conn.fetchrow(
        """
        UPDATE canonical_facts
        SET is_active = false,
            updated_at = now()
        WHERE id = $1::uuid
        RETURNING id::text                  AS id,
                  client_id::text           AS client_id,
                  severity                  AS severity,
                  version                   AS version,
                  authored_by_user_id::text AS authored_by_user_id,
                  body                      AS body,
                  is_active                 AS is_active,
                  created_at::text          AS created_at,
                  updated_at::text          AS updated_at
        """,
        fact_id,
    )
    new_rev = await refresh_canonical_facts_from_table(
        conn, client_id=ctx["client_id"]
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="canonical_facts.deleted",
        target_type="canonical_fact",
        target_id=row["id"],
        metadata={
            "fact_id": row["id"],
            "hard_delete": False,
            "blob_revision": new_rev,
        },
    )
    return CanonicalFactResponse(
        fact=_row_to_model(row),
        blob_revision=new_rev or 0,
    )
