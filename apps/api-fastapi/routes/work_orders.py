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

import json
from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from adapter.dispatch import DispatchError, dispatch_gamma_for_package
from authz.audit_writer import write_audit_row
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
    # Beta-2 phase 0.1 (Q3=B locked: optional with "let Aiden decide" default).
    # When provided, persisted into work_orders.requested_outputs jsonb (Q6=A).
    output_kind: Optional[str] = Field(None, max_length=64)
    template_profile_id: Optional[str] = Field(None, max_length=64)


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

    # Beta-2 phase 0.1 — validate optional requested_outputs.
    requested_outputs: Optional[dict] = None
    if body.template_profile_id is not None or body.output_kind is not None:
        # Either field implies the operator wants to constrain the artifact
        # shape. Resolve template_profile_id to its row to validate
        # tenant + status + (if output_kind given) consistency.
        if body.template_profile_id is not None:
            try:
                tp = await conn.fetchrow(
                    """
                    SELECT id::text             AS id,
                           output_kind::text    AS output_kind,
                           status::text         AS status
                      FROM template_profiles
                     WHERE id = $1::uuid AND client_id = $2::uuid
                    """,
                    body.template_profile_id,
                    ctx["client_id"],
                )
            except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "invalid_template_profile_id",
                        "value": body.template_profile_id,
                    },
                )
            if tp is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "template_profile_not_found",
                        "template_profile_id": body.template_profile_id,
                    },
                )
            if tp["status"] != "active":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "template_profile_not_active",
                        "template_profile_id": body.template_profile_id,
                        "status": tp["status"],
                    },
                )
            if (
                body.output_kind is not None
                and body.output_kind != tp["output_kind"]
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "output_kind_template_mismatch",
                        "output_kind": body.output_kind,
                        "template_profile_output_kind": tp["output_kind"],
                    },
                )
            requested_outputs = {
                "output_kind": tp["output_kind"],
                "template_profile_id": tp["id"],
            }
        else:
            # output_kind alone — sanity-check that at least one published
            # template_profile exists for this tenant+kind.
            row = await conn.fetchrow(
                """
                SELECT count(*)::int AS n
                  FROM template_profiles
                 WHERE client_id = $1::uuid
                   AND output_kind::text = $2
                   AND status = 'active'
                """,
                ctx["client_id"],
                body.output_kind,
            )
            if row is None or int(row["n"]) == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": "no_published_template_for_output_kind",
                        "output_kind": body.output_kind,
                    },
                )
            requested_outputs = {"output_kind": body.output_kind}
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
           submitted_by_user_id, correlation_id, requested_outputs)
        VALUES ($1::uuid, $2, $3, $4, $5::work_order_priority, 'pending',
                $6::uuid, $7, $8::jsonb)
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
        json.dumps(requested_outputs) if requested_outputs is not None else None,
    )

    # Beta-2 phase 0.1 — audit operator-supplied output intent. Emitted only
    # when requested_outputs is non-null (the WO_CREATED audit is implicit
    # via the existing transition write_audit infrastructure; this row
    # captures the intent specifically for downstream PM honor + ops review).
    if requested_outputs is not None:
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="work_order.requested_outputs_set",
            target_type="work_order",
            target_id=row["id"],
            metadata=requested_outputs,
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


# ─── Beta-2 phase 0.2 — POST /work_orders/{id}/render ───────────────────


class RenderResponse(BaseModel):
    ok: bool
    work_order_id: str
    output_package_id: Optional[str] = None
    handoff_id: Optional[str] = None
    external_reference: Optional[str] = None
    gamma_url: Optional[str] = None
    error: Optional[str] = None


@router.post(
    "/{work_order_id}/render",
    response_model=RenderResponse,
    dependencies=[Depends(require_permission_dep("output_package:submit"))],
)
async def render_work_order(
    work_order_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> RenderResponse:
    """Submit the WO's latest gamma_*-kinded output_package to Gamma
    and create the handoff. Used by the Streamlit "Render via Gamma"
    button to close the loop on WOs that produced a package before the
    auto-dispatch hooks landed (or whose initial dispatch failed).

    Idempotent: if the package already has an in-flight handoff this
    returns 409 with the existing handoff_id."""
    pkg = await conn.fetchrow(
        """
        SELECT id::text          AS id,
               output_kind::text AS output_kind
          FROM output_packages
         WHERE work_order_id = $1::uuid
           AND client_id = $2::uuid
           AND output_kind::text LIKE 'gamma_%'
         ORDER BY created_at DESC LIMIT 1
        """,
        work_order_id,
        ctx["client_id"],
    )
    if pkg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_gamma_package",
                "work_order_id": work_order_id,
            },
        )

    try:
        result = await dispatch_gamma_for_package(
            conn,
            output_package_id=pkg["id"],
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
        )
    except DispatchError as exc:
        if exc.kind == "handoff_already_exists":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": exc.kind,
                    "detail": exc.detail,
                    "output_package_id": pkg["id"],
                },
            )
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="adapter_dispatch.failed",
            target_type="output_package",
            target_id=pkg["id"],
            metadata={
                "kind": exc.kind,
                "detail": exc.detail,
                "stage": "manual_render_button",
            },
        )
        return RenderResponse(
            ok=False,
            work_order_id=work_order_id,
            output_package_id=pkg["id"],
            error=f"{exc.kind}: {exc.detail}",
        )

    return RenderResponse(
        ok=True,
        work_order_id=work_order_id,
        output_package_id=result.output_package_id,
        handoff_id=result.handoff_id,
        external_reference=result.external_reference,
        gamma_url=result.gamma_url,
    )
