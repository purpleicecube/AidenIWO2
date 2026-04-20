"""Loop 7 Phase 7.2 — /work_orders routes.

  GET  /work_orders                list WOs in the current tenant
  GET  /work_orders/{id}           single WO
  POST /work_orders/{id}/transition   body: {to, reason?}
  POST /work_orders/{id}/watchdog_expire   body: {reason}

Every mutation gates on the transition helper's declared permissions;
the route itself enforces a generic `work_order:read` on listing + get,
and `work_order:update` on transitions is enforced inside the helper.
"""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)
from wo_wf.transitions import (
    IllegalTransition,
    PermissionDenied,
    RowNotFound,
    transition_work_order,
    watchdog_expire_work_order,
)

router = APIRouter(prefix="/work_orders", tags=["work_orders"])


class WorkOrderRow(BaseModel):
    id: str
    client_id: str
    title: str
    description: Optional[str] = None
    type: str
    priority: str
    status: str
    submitted_by_user_id: Optional[str] = None
    correlation_id: Optional[str] = None
    created_at: str
    updated_at: str


class ListWorkOrdersResponse(BaseModel):
    work_orders: list[WorkOrderRow]


class TransitionRequest(BaseModel):
    to: str = Field(..., description="Target status")
    reason: Optional[str] = None


class WatchdogRequest(BaseModel):
    reason: str


class TransitionResponse(BaseModel):
    from_: str = Field(..., alias="from")
    to: str
    event: str
    cycle_id: Optional[str] = None

    class Config:
        populate_by_name = True


@router.get(
    "",
    response_model=ListWorkOrdersResponse,
    dependencies=[Depends(require_permission_dep("work_order:read"))],
)
async def list_work_orders(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ListWorkOrdersResponse:
    rows = await conn.fetch(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               title,
               description,
               type,
               priority::text AS priority,
               status::text AS status,
               submitted_by_user_id::text AS submitted_by_user_id,
               correlation_id,
               created_at::text AS created_at,
               updated_at::text AS updated_at
        FROM work_orders
        ORDER BY created_at DESC
        LIMIT 200
        """
    )
    return ListWorkOrdersResponse(
        work_orders=[WorkOrderRow(**dict(r)) for r in rows]
    )


@router.get(
    "/{work_order_id}",
    response_model=WorkOrderRow,
    dependencies=[Depends(require_permission_dep("work_order:read"))],
)
async def get_work_order(
    work_order_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> WorkOrderRow:
    row = await conn.fetchrow(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               title,
               description,
               type,
               priority::text AS priority,
               status::text AS status,
               submitted_by_user_id::text AS submitted_by_user_id,
               correlation_id,
               created_at::text AS created_at,
               updated_at::text AS updated_at
        FROM work_orders WHERE id = $1
        """,
        work_order_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "work_order_id": work_order_id},
        )
    return WorkOrderRow(**dict(row))


@router.post("/{work_order_id}/transition", response_model=TransitionResponse)
async def transition_wo(
    work_order_id: str,
    body: TransitionRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> TransitionResponse:
    try:
        result = await transition_work_order(
            conn,
            work_order_id=work_order_id,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            to=body.to,
            reason=body.reason,
        )
    except PermissionDenied as err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "permission_denied",
                "permission": err.permission,
                "reason": err.reason,
                "role": err.role,
            },
        )
    except IllegalTransition as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "illegal_transition",
                "code": err.code,
                "from": err.from_,
                "to": err.to,
            },
        )
    except RowNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "work_order_id": work_order_id},
        )
    return TransitionResponse(
        **{
            "from": result["from"],
            "to": result["to"],
            "event": result["event"],
            "cycle_id": result.get("cycle_id"),
        }
    )


@router.post(
    "/{work_order_id}/watchdog_expire", response_model=TransitionResponse
)
async def watchdog_expire(
    work_order_id: str,
    body: WatchdogRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> TransitionResponse:
    try:
        result = await watchdog_expire_work_order(
            conn,
            work_order_id=work_order_id,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            reason=body.reason,
        )
    except PermissionDenied as err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "permission_denied",
                "permission": err.permission,
                "reason": err.reason,
                "role": err.role,
            },
        )
    except IllegalTransition as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "illegal_transition",
                "code": err.code,
                "from": err.from_,
                "to": err.to,
            },
        )
    except RowNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "work_order_id": work_order_id},
        )
    return TransitionResponse(
        **{
            "from": result["from"],
            "to": result["to"],
            "event": result["event"],
            "cycle_id": result.get("cycle_id"),
        }
    )
