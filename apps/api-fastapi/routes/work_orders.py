"""Loop 7 Phase 7.2 — /work_orders routes.

  GET  /work_orders                list WOs in the current tenant
  GET  /work_orders/{id}           single WO
  POST /work_orders/{id}/transition       body: {to, reason?}
  POST /work_orders/{id}/watchdog_expire  body: {reason}

Loop Xi — operator recovery loop (reopen + edit + redispatch):
  POST /work_orders/{id}/reopen      body: {reason}
  PUT  /work_orders/{id}             body: partial fields incl. template
  POST /work_orders/{id}/redispatch  body: {}

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


# ─── Loop Xi — operator recovery (reopen + edit + redispatch) ──────────


# States from which a WO may be reopened. Mirrors the WO state machine
# spec at contracts/state_machines.py — completed / done / failed all
# transition to processing under the (execution_cycle:reopen +
# work_order:update) gate.
_REOPENABLE_FROM = ("completed", "done", "failed")

# States in which inline edits are accepted. Anything non-terminal
# where operator amendment is operationally useful: post-create
# (`pending`), post-reopen / mid-flight (`processing`), mid-flight
# stuck states (`blocked`, `awaiting_operator`), and parked
# (`deferred`). Terminal states (`completed` / `done` / `failed` /
# `cancelled`) are intentionally rejected here — operator must
# reopen first via POST /reopen for the closed-loop terminal cases,
# and `cancelled` is a deliberately one-way trip.
#
# BUG-060 (2026-05-10): widened from ("pending", "processing") to
# include the three other non-terminal states. Operator-reported
# trap: a WO in `awaiting_operator` could not be edited without a
# manual status hop through `processing`, even though
# `awaiting_operator` is exactly the state where operator
# amendment is most likely.
_EDITABLE_STATUSES = (
    "pending",
    "processing",
    "blocked",
    "awaiting_operator",
    "deferred",
)

# States from which the operator may force a fresh dispatch. Mirrors
# _EDITABLE_STATUSES so the recovery flow is consistent: every state
# where you can Edit, you can also Redispatch. The dispatch path
# itself idempotently transitions `pending` -> `processing` and is
# safe to call from `blocked` / `awaiting_operator` / `deferred`
# (those produce a fresh dispatch attempt; the prior orchestration
# state stays in audit history).
_REDISPATCHABLE_STATUSES = _EDITABLE_STATUSES

# Allowed `type` enum values on partial-update. Reuses the same surface
# as POST /work_orders (no DB enum — `type` is a free-form short string
# the orchestrator routes on).
_ALLOWED_TYPES = (
    "content_brief",
    "deck_build",
    "data_analysis",
    "research",
    "code_change",
    "decision_request",
    "ops_task",
    "general",
)


class ReopenRequest(BaseModel):
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Operator-supplied reason for reopening. Required.",
    )


class ReopenResponse(BaseModel):
    work_order_id: str
    from_status: str = Field(..., alias="from")
    to_status: str = Field(..., alias="to")
    cycle_id: Optional[str] = None
    superseded_executions: int = Field(
        0,
        description=(
            "Count of in-flight workflow_executions cancelled on reopen "
            "so the next dispatch creates a fresh execution chain."
        ),
    )

    class Config:
        populate_by_name = True


class EditRequest(BaseModel):
    """Partial-update payload. Every field is Optional; only those
    explicitly supplied are written. `template_profile_id=None` is
    treated as 'leave unchanged' (use a sentinel like '' to clear in a
    future loop if needed; current scope is set-only)."""

    title: Optional[str] = Field(None, min_length=1, max_length=240)
    description: Optional[str] = Field(None, max_length=8000)
    type: Optional[str] = Field(None, max_length=64)
    priority: Optional[str] = Field(None)
    template_profile_id: Optional[str] = Field(None, max_length=64)


class RedispatchRequest(BaseModel):
    """Empty body for now. The redispatch path always reuses the WO's
    current title + description. Operators who want to override intake
    should edit the WO first via PUT /work_orders/{id}."""


@router.post(
    "/{work_order_id}/reopen",
    response_model=ReopenResponse,
    dependencies=[Depends(require_permission_dep("work_order:update"))],
)
async def reopen_work_order(
    work_order_id: str,
    body: ReopenRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ReopenResponse:
    """Reopen a terminal WO back to `processing` so it can be edited
    and re-dispatched. Mirrors IWO2's POST /api/work-orders/:id/reopen
    contract: requires a non-empty reason, allowed only from terminal
    states, writes a new execution_cycles row with trigger='reopen' via
    the central transition helper.

    IWO2 also resets stale orchestration linkage on the WO row
    (assigned_sub_agent_id / workflow_execution_id). IWO3's schema
    keeps that linkage on `workflow_executions.work_order_id`
    (back-reference), so the equivalent is to cancel any in-flight
    workflow_executions tied to this WO. Prior `completed` /
    `failed` / `cancelled` executions stay as audit history; only
    `pending` / `running` ones get superseded."""
    row = await conn.fetchrow(
        """
        SELECT id::text     AS id,
               status::text AS status
          FROM work_orders
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        work_order_id,
        ctx["client_id"],
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "work_order_id": work_order_id},
        )
    if row["status"] not in _REOPENABLE_FROM:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "not_reopenable",
                "current_status": row["status"],
                "allowed_from": list(_REOPENABLE_FROM),
            },
        )

    try:
        result = await transition_work_order(
            conn,
            work_order_id=work_order_id,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            to="processing",
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
        # Defensive — the pre-check above should make this unreachable.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "illegal_transition",
                "code": err.code,
                "from": err.from_,
                "to": err.to,
            },
        )

    # Cancel any in-flight workflow_executions linked to this WO so the
    # next dispatch creates a fresh chain. The UPDATE is RLS-scoped via
    # the tenant connection. We don't go through the WF transition
    # helper because (a) requires_cycle false-positives would write
    # noisy execution_cycles and (b) the WF state machine `cancelled`
    # transition demands `workflow:cancel` which the operator may not
    # hold even with `work_order:update`.
    # lint:bypass-rls-explain="tenant-scoped connection — RLS filters by client_id"
    superseded_count = await conn.fetchval(
        """
        WITH cancelled AS (
          UPDATE workflow_executions
             SET status = 'cancelled',
                 completed_at = now()
           WHERE work_order_id = $1::uuid
             AND client_id = $2::uuid
             AND status IN ('pending', 'running')
          RETURNING id
        )
        SELECT count(*)::int FROM cancelled
        """,
        work_order_id,
        ctx["client_id"],
    )

    return ReopenResponse(
        **{
            "work_order_id": work_order_id,
            "from": result["from"],
            "to": result["to"],
            "cycle_id": result.get("cycle_id"),
            "superseded_executions": int(superseded_count or 0),
        }
    )


@router.put(
    "/{work_order_id}",
    response_model=WorkOrderRow,
    dependencies=[Depends(require_permission_dep("work_order:update"))],
)
async def edit_work_order(
    work_order_id: str,
    body: EditRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> WorkOrderRow:
    """Inline-edit a non-terminal WO. Accepts partial updates on
    title / description / type / priority / requested_outputs.template_profile_id.
    The status field is intentionally NOT mutable here — status changes
    must go through the transition helper (POST /transition) so the
    state machine + audit cycle invariants hold.

    Slight upgrade over IWO2: explicit template_profile_id selection
    (IWO2 only allows prose hinting via description). Templates are
    validated tenant-scoped + active before persisting."""
    # Validate the WO exists, scope, and editable status.
    row = await conn.fetchrow(
        """
        SELECT id::text             AS id,
               client_id::text      AS client_id,
               status::text         AS status,
               requested_outputs
          FROM work_orders
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        work_order_id,
        ctx["client_id"],
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "work_order_id": work_order_id},
        )
    if row["status"] not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "not_editable",
                "current_status": row["status"],
                "allowed_statuses": list(_EDITABLE_STATUSES),
                "hint": (
                    "Reopen the work order first (POST /reopen) if it is in "
                    "a terminal state."
                ),
            },
        )

    # Validate non-None field values against narrow vocabularies.
    if body.priority is not None and body.priority not in {
        "low",
        "medium",
        "high",
        "critical",
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_priority", "priority": body.priority},
        )
    if body.type is not None and body.type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_type",
                "type": body.type,
                "allowed": list(_ALLOWED_TYPES),
            },
        )

    # Resolve template_profile_id if supplied — same validation as
    # create_work_order: tenant-scoped + active.
    new_requested_outputs: Optional[dict] = None
    if body.template_profile_id is not None:
        try:
            tp = await conn.fetchrow(
                """
                SELECT id::text          AS id,
                       output_kind::text AS output_kind,
                       status::text      AS status
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
        # Merge into existing requested_outputs (preserve other keys
        # like output_kind if already set on the WO).
        existing = (
            json.loads(row["requested_outputs"])
            if isinstance(row["requested_outputs"], str)
            else (row["requested_outputs"] or {})
        )
        new_requested_outputs = {
            **existing,
            "output_kind": tp["output_kind"],
            "template_profile_id": tp["id"],
        }

    # Build the dynamic UPDATE. Only set fields the operator supplied.
    sets: list[str] = []
    params: list[Any] = []
    changed_fields: list[str] = []

    def _set(col: str, value: Any, *, sql_cast: str = "") -> None:
        params.append(value)
        sets.append(f"{col} = ${len(params)}{sql_cast}")
        changed_fields.append(col)

    if body.title is not None:
        _set("title", body.title)
    if body.description is not None:
        _set("description", body.description)
    if body.type is not None:
        _set("type", body.type)
    if body.priority is not None:
        _set("priority", body.priority, sql_cast="::work_order_priority")
    if new_requested_outputs is not None:
        params.append(json.dumps(new_requested_outputs))
        sets.append(f"requested_outputs = ${len(params)}::jsonb")
        changed_fields.append("requested_outputs")

    if not sets:
        # No-op edit — still surface the current row for client refresh.
        # No audit emission for a noop.
        full = await conn.fetchrow(
            """
            SELECT id::text AS id,
                   client_id::text AS client_id,
                   title, description, type,
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
        return WorkOrderRow(**dict(full))

    # Append updated_at + WHERE binds.
    sets.append("updated_at = now()")
    params.append(work_order_id)
    wo_id_idx = len(params)
    params.append(ctx["client_id"])
    cid_idx = len(params)

    sql = f"""
        UPDATE work_orders
           SET {', '.join(sets)}
         WHERE id = ${wo_id_idx}::uuid AND client_id = ${cid_idx}::uuid
        RETURNING id::text AS id,
                  client_id::text AS client_id,
                  title, description, type,
                  priority::text AS priority,
                  status::text AS status,
                  submitted_by_user_id::text AS submitted_by_user_id,
                  correlation_id,
                  created_at::text AS created_at,
                  updated_at::text AS updated_at
    """
    updated = await conn.fetchrow(sql, *params)

    # Audit. The metadata captures both the diff vocabulary and the
    # full new requested_outputs jsonb shape (so reviewers can
    # reconstruct template assignment without re-querying).
    audit_meta: dict[str, Any] = {
        "changed_fields": changed_fields,
        "from_status": row["status"],
    }
    if new_requested_outputs is not None:
        audit_meta["requested_outputs"] = new_requested_outputs
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="work_order.edited",
        target_type="work_order",
        target_id=work_order_id,
        metadata=audit_meta,
    )

    return WorkOrderRow(**dict(updated))


@router.post(
    "/{work_order_id}/redispatch",
    dependencies=[Depends(require_permission_dep("work_order:update"))],
)
async def redispatch_work_order(
    work_order_id: str,
    _body: RedispatchRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> dict[str, Any]:
    """Re-fire the dispatch pipeline for a WO that's been reopened or
    is otherwise pending. Writes a `work_order.redispatched` audit row
    upfront, then delegates to the existing
    POST /work_orders/{id}/dispatch helper so we don't fork the
    orchestration logic.

    Returns the same shape as /dispatch with an extra `redispatched`
    flag so the UI can render an op-level confirmation."""
    row = await conn.fetchrow(
        """
        SELECT status::text AS status
          FROM work_orders
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        work_order_id,
        ctx["client_id"],
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "work_order_id": work_order_id},
        )
    if row["status"] not in _REDISPATCHABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "not_redispatchable",
                "current_status": row["status"],
                "allowed_statuses": list(_REDISPATCHABLE_STATUSES),
                "hint": (
                    "Reopen a terminal WO first (POST /reopen) before "
                    "redispatching."
                ),
            },
        )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="work_order.redispatched",
        target_type="work_order",
        target_id=work_order_id,
        metadata={"from_status": row["status"]},
    )

    # Delegate to the existing dispatch handler. Lazy-imported to avoid
    # a circular import at module load (routes.dispatch imports
    # transitions which routes.work_orders also uses; the lazy hop
    # keeps the dependency graph linear).
    from routes.dispatch import DispatchRequest, dispatch_work_order

    result = await dispatch_work_order(
        work_order_id=work_order_id,
        body=DispatchRequest(intake_override=None),
        ctx=ctx,
        conn=conn,
    )
    payload = result.model_dump()
    payload["redispatched"] = True
    return payload
