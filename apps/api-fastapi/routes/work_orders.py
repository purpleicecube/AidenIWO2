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


class WorkOrderMetricsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    reopened_count: int


class CreateWorkOrderRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=240)
    description: Optional[str] = None
    type: str = Field("content_brief", max_length=64)
    priority: str = Field("medium")
    correlation_id: Optional[str] = Field(None, max_length=128)


@router.get(
    "/metrics",
    response_model=WorkOrderMetricsResponse,
    dependencies=[Depends(require_permission_dep("work_order:read"))],
)
async def work_order_metrics(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> WorkOrderMetricsResponse:
    # By-status counts (tenant-scoped via RLS).
    by_status_rows = await conn.fetch(
        """
        SELECT status::text AS status, count(*)::int AS n
        FROM work_orders GROUP BY status
        """
    )
    by_status = {r["status"]: r["n"] for r in by_status_rows}
    total = sum(by_status.values())
    # Reopened = count of execution_cycles with trigger='reopen'.
    # lint:bypass-rls-explain="tenant-scoped connection (iwo3_app role + app.current_client_id GUC set) — RLS filters execution_cycles by client_id transparently"
    rc = await conn.fetchrow(
        """
        SELECT count(*)::int AS n FROM execution_cycles
        WHERE trigger = 'reopen'
        """
    )
    reopened = int(rc["n"]) if rc else 0
    return WorkOrderMetricsResponse(
        total=total, by_status=by_status, reopened_count=reopened
    )


@router.post(
    "",
    response_model=WorkOrderRow,
    dependencies=[Depends(require_permission_dep("work_order:create"))],
)
async def create_work_order(
    body: CreateWorkOrderRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> WorkOrderRow:
    # Validate priority against the enum to surface the error as 422
    # rather than a Postgres 23514 check-constraint leak.
    if body.priority not in {"low", "medium", "high", "critical"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_priority", "priority": body.priority},
        )
    # Beta-1 ε.3 / Q8 — chat-driven creates carry a partial UNIQUE on
    # (client_id, correlation_id) WHERE correlation_id LIKE 'chat:%'
    # (migration 0016). For chat correlations, look up the existing WO
    # BEFORE the INSERT to avoid leaving the asyncpg transaction in a
    # failed state (which would break a post-violation lookup). The
    # partial-UNIQUE remains the canonical race-safe gate at the DB
    # layer; this pre-flight is the operator-friendly path.
    if body.correlation_id and body.correlation_id.startswith("chat:"):
        existing = await conn.fetchrow(
            """
            SELECT id::text AS id, title
              FROM work_orders
             WHERE client_id = $1::uuid AND correlation_id = $2
            """,
            ctx["client_id"],
            body.correlation_id,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "duplicate_correlation_id",
                    "correlation_id": body.correlation_id,
                    "existing_work_order_id": existing["id"],
                    "existing_title": existing["title"],
                },
            )

    row = await conn.fetchrow(
        """
        INSERT INTO work_orders
          (client_id, title, description, type, priority, status,
           submitted_by_user_id, correlation_id)
        VALUES ($1::uuid, $2, $3, $4, $5::work_order_priority, 'pending',
                $6::uuid, $7)
        RETURNING id::text AS id,
                  client_id::text AS client_id,
                  title, description, type,
                  priority::text AS priority,
                  status::text AS status,
                  submitted_by_user_id::text AS submitted_by_user_id,
                  correlation_id,
                  created_at::text AS created_at,
                  updated_at::text AS updated_at
        """,
        ctx["client_id"],
        body.title,
        body.description,
        body.type,
        body.priority,
        ctx["user_id"],
        body.correlation_id,
    )
    return WorkOrderRow(**dict(row))


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
