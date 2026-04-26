"""Loop 7 Phase 7.1 — /tenants route.
   Beta-1.5 phase 2 — adds /tenants/me/settings (Q1 ceiling editor).

Lists the tenants (clients) the current user has an active membership
on. Read-only at Loop 7. Beta-1.5 phase 2 introduces the per-tenant
settings surface (Q1 LLM ceiling editor). Settings live on `clients`;
the read path is any-tenant-member; the write path requires
`system:admin` per Loop 4 §Q2 + the credential-edit precedent.

Audit emissions (locked under BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS):
  client.settings_updated   on PATCH /tenants/me/settings
"""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from authz.audit_writer import write_audit_row
from deps import (
    current_user_context,
    get_db_connection,
    get_tenant_scoped_connection,
    require_permission_dep,
)
from runtime.budgets import DEFAULT_PER_WO_CEILING

router = APIRouter(prefix="/tenants", tags=["tenants"])


_CEILING_MIN = 1_000
_CEILING_MAX = 1_000_000


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


# ── Beta-1.5 phase 2 / Q1 — tenant settings (per-tenant LLM ceiling) ──


class TenantSettings(BaseModel):
    client_id: str
    designation: str
    llm_per_wo_ceiling: int
    llm_per_wo_ceiling_is_default: bool
    ceiling_min: int = _CEILING_MIN
    ceiling_max: int = _CEILING_MAX


class UpdateTenantSettingsRequest(BaseModel):
    # Set explicitly to an int to override; set to null to revert to
    # platform default (DEFAULT_PER_WO_CEILING).
    llm_per_wo_ceiling: Optional[int] = Field(
        None, ge=_CEILING_MIN, le=_CEILING_MAX
    )
    revert_to_default: bool = False


def _settings_from_row(row: asyncpg.Record) -> TenantSettings:
    raw = row["llm_per_wo_ceiling"]
    is_default = raw is None
    return TenantSettings(
        client_id=row["client_id"],
        designation=row["designation"],
        llm_per_wo_ceiling=int(raw) if raw is not None else DEFAULT_PER_WO_CEILING,
        llm_per_wo_ceiling_is_default=is_default,
    )


@router.get(
    "/me/settings",
    response_model=TenantSettings,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def get_my_tenant_settings(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> TenantSettings:
    row = await conn.fetchrow(
        """
        SELECT id::text   AS client_id,
               designation,
               llm_per_wo_ceiling
          FROM clients
         WHERE id = $1::uuid
        """,
        ctx["client_id"],
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "client_not_found"},
        )
    return _settings_from_row(row)


@router.patch(
    "/me/settings",
    response_model=TenantSettings,
    dependencies=[Depends(require_permission_dep("system:admin"))],
)
async def update_my_tenant_settings(
    body: UpdateTenantSettingsRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> TenantSettings:
    """Beta-1.5 phase 2 / Q1 — admin-only ceiling editor.

    Two write modes:
      * ``llm_per_wo_ceiling = N`` — pin tenant ceiling to N tokens.
      * ``revert_to_default = true`` — clear the override; runtime falls
        back to ``DEFAULT_PER_WO_CEILING`` via ``resolve_per_wo_ceiling``.
    """
    if body.revert_to_default:
        new_value: Optional[int] = None
    elif body.llm_per_wo_ceiling is not None:
        new_value = int(body.llm_per_wo_ceiling)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "no_change",
                "message": (
                    "Provide llm_per_wo_ceiling or set revert_to_default=true"
                ),
            },
        )

    prev = await conn.fetchval(
        "SELECT llm_per_wo_ceiling FROM clients WHERE id = $1::uuid",
        ctx["client_id"],
    )

    # lint:bypass-rls-explain="clients is RLS-FORCED on tenant-scoped connection; WHERE id matches the active tenant only."
    row = await conn.fetchrow(
        """
        UPDATE clients
           SET llm_per_wo_ceiling = $1
         WHERE id = $2::uuid
        RETURNING id::text   AS client_id,
                  designation,
                  llm_per_wo_ceiling
        """,
        new_value,
        ctx["client_id"],
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "client_not_found"},
        )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="client.settings_updated",
        target_type="client",
        target_id=ctx["client_id"],
        metadata={
            "setting": "llm_per_wo_ceiling",
            "previous": int(prev) if prev is not None else None,
            "new": new_value,
            "revertToDefault": body.revert_to_default,
        },
    )
    return _settings_from_row(row)
