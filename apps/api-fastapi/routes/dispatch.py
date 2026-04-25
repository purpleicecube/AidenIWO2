"""Pre-Beta β.3 — end-to-end dispatch routes.

Closes the Alpha truth gap where Tier 1 / Tier 1.5 / Tier 2 helpers
existed but no product flow reached them. Two routes:

  POST /work_orders/{id}/dispatch
       Reads the WO (title + description), runs Aiden Tier 1, branches:
         work_order_brief  → invoke Tier 2 + persist output_package
         workflow_brief    → instantiate workflow + step_runs
         clarification     → return question; no DB changes
       RBAC: work_order:update.

  POST /workflows/{execution_id}/run_next_step
       Pick the first `pending` step_run for an execution and execute
       it (Tier 2). Returns the step result + the next pending step
       (or null if the workflow finished).
       RBAC: workflow_step_run:update.

Both paths are inline (synchronous); async-polling for Tier 2 results
is a Beta concern. Output packages with `gamma_*` kinds get picked up
by the existing Loop 9 handoff worker.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from authz.audit_writer import write_audit_row
from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)
from runtime.budgets import LlmBudgetExceeded
from runtime.tier_1_aiden import (
    AidenInvocationError,
    AidenNoConfig,
    invoke_aiden_tier_1,
)
from runtime.tier_1_5_pm import (
    PmError,
    instantiate_workflow_from_brief,
)
from runtime.tier_2_subagents import (
    Tier2Error,
    execute_step_run,
    invoke_tier_2,
    produce_output_package,
)
from wo_wf.transitions import (
    IllegalTransition,
    PermissionDenied,
    RowNotFound,
    transition_work_order,
)


router = APIRouter(tags=["dispatch"])


# ── POST /work_orders/{id}/dispatch ───────────────────────────────────


class DispatchRequest(BaseModel):
    intake_override: Optional[str] = Field(
        None,
        max_length=8000,
        description=(
            "Override the intake text Aiden Tier 1 sees. Defaults to "
            "the WO's title + description. Useful when the operator "
            "wants to clarify intent without re-saving the WO."
        ),
    )


class DispatchResponse(BaseModel):
    ok: bool
    decision_kind: Optional[str] = None
    work_order_id: str
    output_package_id: Optional[str] = None
    workflow_execution_id: Optional[str] = None
    step_run_ids: Optional[list[str]] = None
    clarification_question: Optional[str] = None
    error: Optional[str] = None


async def _safe_transition_processing(
    conn: asyncpg.Connection,
    *,
    work_order_id: str,
    client_id: str,
    actor_user_id: str,
    reason: str,
) -> None:
    """Move a WO to `processing` if it isn't already; swallow IllegalTransition
    (already in a downstream state) so the caller's happy path isn't blocked."""
    try:
        await transition_work_order(
            conn,
            work_order_id=work_order_id,
            client_id=client_id,
            actor_user_id=actor_user_id,
            to="processing",
            reason=reason,
        )
    except IllegalTransition:
        pass  # already past pending; that's fine
    except RowNotFound:
        pass  # caller already raised 404 if needed


@router.post(
    "/work_orders/{work_order_id}/dispatch",
    response_model=DispatchResponse,
    dependencies=[Depends(require_permission_dep("work_order:update"))],
)
async def dispatch_work_order(
    work_order_id: str,
    body: DispatchRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> DispatchResponse:
    try:
        wo = await conn.fetchrow(
            """
            SELECT id::text         AS id,
                   title,
                   description,
                   status::text     AS status
              FROM work_orders
             WHERE id = $1::uuid AND client_id = $2::uuid
            """,
            work_order_id,
            ctx["client_id"],
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_work_order_id", "value": work_order_id},
        )
    if wo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "work_order_id": work_order_id},
        )

    intake_text = (
        body.intake_override
        or f"{wo['title']}\n\n{wo['description'] or ''}".strip()
    )

    try:
        decision = await invoke_aiden_tier_1(
            conn,
            intake_text=intake_text,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            work_order_id=wo["id"],
        )
    except AidenNoConfig as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_aiden_config", "detail": str(exc)},
        )
    except LlmBudgetExceeded as exc:
        return DispatchResponse(
            ok=False,
            work_order_id=wo["id"],
            error=(
                f"llm_budget_exceeded: used {exc.already_used} of ceiling "
                f"{exc.ceiling}"
            ),
        )
    except AidenInvocationError as exc:
        return DispatchResponse(
            ok=False,
            work_order_id=wo["id"],
            error=f"{exc.kind}: {exc}",
        )

    if decision.decision_kind == "clarification":
        c = decision.clarification
        return DispatchResponse(
            ok=False,
            decision_kind="clarification",
            work_order_id=wo["id"],
            clarification_question=(
                c.question if c else "(no question returned)"
            ),
        )

    await _safe_transition_processing(
        conn,
        work_order_id=wo["id"],
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        reason=f"dispatch:{decision.decision_kind}",
    )

    if decision.decision_kind == "work_order_brief":
        brief = decision.work_order_brief
        assert brief is not None
        try:
            envelope = await invoke_tier_2(
                conn,
                role=brief.assigned_role,
                intake_text=intake_text,
                content_blocks=brief.content_blocks or {},
                work_order_id=wo["id"],
                client_id=ctx["client_id"],
                actor_user_id=ctx["user_id"],
            )
        except LlmBudgetExceeded as exc:
            return DispatchResponse(
                ok=False,
                decision_kind="work_order_brief",
                work_order_id=wo["id"],
                error=(
                    f"tier_2_budget_exceeded: used {exc.already_used} "
                    f"of ceiling {exc.ceiling}"
                ),
            )
        except Tier2Error as exc:
            return DispatchResponse(
                ok=False,
                decision_kind="work_order_brief",
                work_order_id=wo["id"],
                error=f"{exc.args[0] if exc.args else 'tier_2_failed'}: {exc}",
            )

        pkg_id = await produce_output_package(
            conn,
            envelope=envelope,
            title=decision.title or wo["title"],
            work_order_id=wo["id"],
            workflow_execution_id=None,
            template_profile_id=None,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            correlation_id=f"dispatch:{wo['id']}",
        )
        return DispatchResponse(
            ok=True,
            decision_kind="work_order_brief",
            work_order_id=wo["id"],
            output_package_id=pkg_id,
        )

    if decision.decision_kind == "workflow_brief":
        brief = decision.workflow_brief
        assert brief is not None
        try:
            inst = await instantiate_workflow_from_brief(
                conn,
                brief=brief,
                intake_text=intake_text,
                aiden_summary=decision.summary,
                work_order_id=wo["id"],
                client_id=ctx["client_id"],
                actor_user_id=ctx["user_id"],
            )
        except PmError as exc:
            return DispatchResponse(
                ok=False,
                decision_kind="workflow_brief",
                work_order_id=wo["id"],
                error=f"pm_failed: {exc}",
            )

        return DispatchResponse(
            ok=True,
            decision_kind="workflow_brief",
            work_order_id=wo["id"],
            workflow_execution_id=inst.workflow_execution_id,
            step_run_ids=list(inst.step_run_ids),
        )

    return DispatchResponse(
        ok=False,
        decision_kind=decision.decision_kind,
        work_order_id=wo["id"],
        error=f"unsupported_decision_kind: {decision.decision_kind}",
    )


# ── POST /workflows/{execution_id}/run_next_step ──────────────────────


class RunNextStepResponse(BaseModel):
    ok: bool
    execution_id: str
    step_run_id: Optional[str] = None
    step_key: Optional[str] = None
    output_package_id: Optional[str] = None
    next_step_run_id: Optional[str] = None
    workflow_finished: bool = False
    error: Optional[str] = None


@router.post(
    "/workflows/{execution_id}/run_next_step",
    response_model=RunNextStepResponse,
    dependencies=[Depends(require_permission_dep("workflow_step_run:update"))],
)
async def run_next_step(
    execution_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> RunNextStepResponse:
    try:
        exec_row = await conn.fetchrow(
            """
            SELECT id::text AS id, status::text AS status
              FROM workflow_executions
             WHERE id = $1::uuid AND client_id = $2::uuid
            """,
            execution_id,
            ctx["client_id"],
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_execution_id", "value": execution_id},
        )
    if exec_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "execution_not_found", "id": execution_id},
        )

    next_pending = await conn.fetchrow(
        """
        SELECT id::text AS id, step_key, step_order
          FROM workflow_step_runs
         WHERE execution_id = $1::uuid
           AND status = 'pending'::workflow_step_run_status
         ORDER BY step_order ASC
         LIMIT 1
        """,
        execution_id,
    )
    if next_pending is None:
        return RunNextStepResponse(
            ok=True,
            execution_id=execution_id,
            workflow_finished=True,
        )

    try:
        result = await execute_step_run(
            conn,
            step_run_id=next_pending["id"],
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
        )
    except Tier2Error as exc:
        return RunNextStepResponse(
            ok=False,
            execution_id=execution_id,
            step_run_id=next_pending["id"],
            step_key=next_pending["step_key"],
            error=f"{exc.args[0] if exc.args else 'tier_2_failed'}: {exc}",
        )

    follow_up = await conn.fetchrow(
        """
        SELECT id::text AS id
          FROM workflow_step_runs
         WHERE execution_id = $1::uuid
           AND status = 'pending'::workflow_step_run_status
         ORDER BY step_order ASC
         LIMIT 1
        """,
        execution_id,
    )

    return RunNextStepResponse(
        ok=True,
        execution_id=execution_id,
        step_run_id=next_pending["id"],
        step_key=next_pending["step_key"],
        output_package_id=result.output_package_id,
        next_step_run_id=follow_up["id"] if follow_up else None,
        workflow_finished=follow_up is None,
    )
