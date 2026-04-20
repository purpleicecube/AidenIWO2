"""Loop 7 Phase 7.2 — /output_packages + /output_handoffs read routes."""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)

router = APIRouter(tags=["output"])


class OutputPackageRow(BaseModel):
    id: str
    client_id: str
    work_order_id: Optional[str] = None
    output_kind: str
    title: str
    status: str
    created_at: str


class ListOutputPackagesResponse(BaseModel):
    output_packages: list[OutputPackageRow]


class OutputHandoffRow(BaseModel):
    id: str
    client_id: str
    output_package_id: Optional[str] = None
    external_destination: Optional[str] = None
    external_reference: Optional[str] = None
    status: str
    candidate_status: str
    candidate_group_id: Optional[str] = None
    created_at: str


class ListOutputHandoffsResponse(BaseModel):
    output_handoffs: list[OutputHandoffRow]


@router.get(
    "/output_packages",
    response_model=ListOutputPackagesResponse,
    dependencies=[Depends(require_permission_dep("output_package:read"))],
)
async def list_output_packages(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ListOutputPackagesResponse:
    rows = await conn.fetch(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               work_order_id::text AS work_order_id,
               output_kind::text AS output_kind,
               title,
               status::text AS status,
               created_at::text AS created_at
        FROM output_packages ORDER BY created_at DESC LIMIT 200
        """
    )
    return ListOutputPackagesResponse(
        output_packages=[OutputPackageRow(**dict(r)) for r in rows]
    )


@router.get(
    "/output_packages/{package_id}",
    response_model=OutputPackageRow,
    dependencies=[Depends(require_permission_dep("output_package:read"))],
)
async def get_output_package(
    package_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> OutputPackageRow:
    row = await conn.fetchrow(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               work_order_id::text AS work_order_id,
               output_kind::text AS output_kind,
               title,
               status::text AS status,
               created_at::text AS created_at
        FROM output_packages WHERE id = $1
        """,
        package_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "package_id": package_id},
        )
    return OutputPackageRow(**dict(row))


@router.get(
    "/output_handoffs",
    response_model=ListOutputHandoffsResponse,
    dependencies=[Depends(require_permission_dep("output_handoff:read"))],
)
async def list_output_handoffs(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ListOutputHandoffsResponse:
    rows = await conn.fetch(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               output_package_id::text AS output_package_id,
               external_destination,
               external_reference,
               status::text AS status,
               candidate_status::text AS candidate_status,
               candidate_group_id::text AS candidate_group_id,
               created_at::text AS created_at
        FROM output_handoffs ORDER BY created_at DESC LIMIT 200
        """
    )
    return ListOutputHandoffsResponse(
        output_handoffs=[OutputHandoffRow(**dict(r)) for r in rows]
    )


@router.get(
    "/output_handoffs/{handoff_id}",
    response_model=OutputHandoffRow,
    dependencies=[Depends(require_permission_dep("output_handoff:read"))],
)
async def get_output_handoff(
    handoff_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> OutputHandoffRow:
    row = await conn.fetchrow(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               output_package_id::text AS output_package_id,
               external_destination,
               external_reference,
               status::text AS status,
               candidate_status::text AS candidate_status,
               candidate_group_id::text AS candidate_group_id,
               created_at::text AS created_at
        FROM output_handoffs WHERE id = $1
        """,
        handoff_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "handoff_id": handoff_id},
        )
    return OutputHandoffRow(**dict(row))
