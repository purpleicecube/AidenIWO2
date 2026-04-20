"""Loop 7 Phase 7.1 — /tenants route.

Lists the tenants (clients) the current user has an active membership
on. Read-only; no mutations. Uses the bypass-path connection so the
query can see rows across tenant boundaries where the user has
memberships — the WHERE clause itself is the scope gate.
"""

from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from deps import current_user_context, get_db_connection

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantMembershipRow(BaseModel):
    client_id: str
    designation: str
    display_name: str
    deployment_mode: str
    status: str
    role: str
    membership_status: str


class TenantsResponse(BaseModel):
    tenants: list[TenantMembershipRow]


@router.get("", response_model=TenantsResponse)
async def list_tenants(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> TenantsResponse:
    rows = await conn.fetch(
        """
        SELECT c.id::text AS client_id,
               c.designation,
               c.display_name,
               c.deployment_mode::text AS deployment_mode,
               c.status::text AS status,
               m.role::text AS role,
               m.status::text AS membership_status
        FROM clients c
        JOIN client_memberships m ON m.client_id = c.id
        WHERE m.user_id = $1 AND m.status = 'active'
        ORDER BY c.designation
        """,
        ctx["user_id"],
    )
    return TenantsResponse(
        tenants=[TenantMembershipRow(**dict(r)) for r in rows]
    )
