"""Loop 7 Phase 7.3 — /audit_log + /permissions/check routes.

GET /audit_log                         tenant-scoped audit rows
GET /permissions/check?permission=...  decider verdict for current user
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from authz.check_permission import check_permission_decide
from deps import (
    current_user_context,
    get_db_connection,
    get_tenant_scoped_connection,
    require_permission_dep,
)

router = APIRouter(tags=["observability"])


class AuditRow(BaseModel):
    id: str
    client_id: str
    actor_user_id: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    metadata: dict[str, Any]
    created_at: str


class AuditLogResponse(BaseModel):
    audit_rows: list[AuditRow]


class PermissionCheckResponse(BaseModel):
    allowed: bool
    reason: str
    role: Optional[str] = None


@router.get(
    "/audit_log",
    response_model=AuditLogResponse,
    dependencies=[Depends(require_permission_dep("audit_log:read"))],
)
async def list_audit_log(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    work_order_id: Optional[str] = Query(None),
    limit: int = Query(200, le=500),
) -> AuditLogResponse:
    if work_order_id is not None:
        rows = await conn.fetch(
            """
            SELECT id::text AS id,
                   client_id::text AS client_id,
                   actor_user_id::text AS actor_user_id,
                   action,
                   target_type,
                   target_id,
                   metadata,
                   created_at::text AS created_at
            FROM action_audit_log
            WHERE target_id = $1 OR metadata->>'work_order_id' = $1
            ORDER BY created_at DESC LIMIT $2
            """,
            work_order_id,
            limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id::text AS id,
                   client_id::text AS client_id,
                   actor_user_id::text AS actor_user_id,
                   action,
                   target_type,
                   target_id,
                   metadata,
                   created_at::text AS created_at
            FROM action_audit_log
            ORDER BY created_at DESC LIMIT $1
            """,
            limit,
        )
    import json as _json

    def _to_dict(md: Any) -> dict[str, Any]:
        if md is None:
            return {}
        if isinstance(md, dict):
            return md
        if isinstance(md, str):
            try:
                return _json.loads(md)
            except Exception:  # noqa: BLE001
                return {}
        return {}

    return AuditLogResponse(
        audit_rows=[
            AuditRow(
                id=r["id"],
                client_id=r["client_id"],
                actor_user_id=r["actor_user_id"],
                action=r["action"],
                target_type=r["target_type"],
                target_id=r["target_id"],
                metadata=_to_dict(r["metadata"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]
    )


@router.get("/permissions/check", response_model=PermissionCheckResponse)
async def check_permission_route(
    permission: Annotated[str, Query(..., description="permission key")],
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> PermissionCheckResponse:
    """Returns the decider's verdict for the current user without
    writing an audit row. Streamlit (Loop 8) uses this to hide/show UI
    actions the user isn't authorised for. Not a gate — callers still
    need to hit a real route that enforces the permission."""
    vocab_rows = await conn.fetch("SELECT permission_key FROM permissions")
    known = [r["permission_key"] for r in vocab_rows]

    mem_rows = await conn.fetch(
        """
        SELECT role::text AS role FROM client_memberships
        WHERE user_id = $1 AND client_id = $2 AND status = 'active'
        LIMIT 1
        """,
        ctx["user_id"],
        ctx["client_id"],
    )
    role = mem_rows[0]["role"] if mem_rows else None

    role_perms: list[str] = []
    if role is not None:
        rp_rows = await conn.fetch(
            """
            SELECT p.permission_key FROM role_permissions rp
            JOIN permissions p ON p.id = rp.permission_id
            WHERE rp.role = $1::membership_role
            """,
            role,
        )
        role_perms = [r["permission_key"] for r in rp_rows]

    grant_rows = await conn.fetch(
        """
        SELECT p.permission_key, pg.grant_type::text AS grant_type
        FROM permission_grants pg
        JOIN permissions p ON p.id = pg.permission_id
        WHERE pg.user_id = $1 AND pg.client_id = $2
        """,
        ctx["user_id"],
        ctx["client_id"],
    )
    from authz.check_permission import UserGrant

    user_grants = [
        UserGrant(
            permission_key=r["permission_key"], grant_type=r["grant_type"]
        )
        for r in grant_rows
    ]
    decision = check_permission_decide(
        role=role,
        role_permissions=role_perms,
        user_grants=user_grants,
        permission=permission,
        known_permissions=known,
    )
    return PermissionCheckResponse(
        allowed=decision.allowed,
        reason=decision.reason,
        role=decision.role,
    )
