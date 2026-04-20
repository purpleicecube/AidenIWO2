"""Loop 7 Phase 7.2 — /workflows + /output_packages + /output_handoffs routes.

Read-only surface for Streamlit Loop 8. The only mutation here is the
workflow status transition (active ↔ paused + archive).
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
    transition_workflow,
)

router = APIRouter(tags=["workflows"])


class WorkflowRow(BaseModel):
    id: str
    client_id: str
    key: str
    display_name: str
    description: Optional[str] = None
    status: str
    created_at: str
    updated_at: str


class ListWorkflowsResponse(BaseModel):
    workflows: list[WorkflowRow]


class WorkflowTransitionRequest(BaseModel):
    to: str = Field(..., description="Target status")
    reason: Optional[str] = None


class WorkflowTransitionResponse(BaseModel):
    from_: str = Field(..., alias="from")
    to: str
    event: str

    class Config:
        populate_by_name = True


@router.get(
    "/workflows",
    response_model=ListWorkflowsResponse,
    dependencies=[Depends(require_permission_dep("workflow:read"))],
)
async def list_workflows(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ListWorkflowsResponse:
    rows = await conn.fetch(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               key,
               display_name,
               description,
               status::text AS status,
               created_at::text AS created_at,
               updated_at::text AS updated_at
        FROM workflows ORDER BY display_name
        """
    )
    return ListWorkflowsResponse(
        workflows=[WorkflowRow(**dict(r)) for r in rows]
    )


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowRow,
    dependencies=[Depends(require_permission_dep("workflow:read"))],
)
async def get_workflow(
    workflow_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> WorkflowRow:
    row = await conn.fetchrow(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               key,
               display_name,
               description,
               status::text AS status,
               created_at::text AS created_at,
               updated_at::text AS updated_at
        FROM workflows WHERE id = $1
        """,
        workflow_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "workflow_id": workflow_id},
        )
    return WorkflowRow(**dict(row))


@router.post(
    "/workflows/{workflow_id}/transition",
    response_model=WorkflowTransitionResponse,
)
async def transition_workflow_route(
    workflow_id: str,
    body: WorkflowTransitionRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> WorkflowTransitionResponse:
    try:
        result = await transition_workflow(
            conn,
            workflow_id=workflow_id,
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
            detail={"error": "not_found", "workflow_id": workflow_id},
        )
    return WorkflowTransitionResponse(
        **{"from": result["from"], "to": result["to"], "event": result["event"]}
    )
