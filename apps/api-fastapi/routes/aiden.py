"""MegaLoop Alpha α.7 — Aiden Tier 1 chat surface for the browser.

  POST /aiden/chat       send `message`; receive a parsed AidenDecision
                         (work_order_brief / workflow_brief /
                         clarification) without persisting a work_order.
                         The browser renders the decision and may ask
                         the operator to confirm before promoting it
                         into a real WO via the existing
                         /work_orders + workflow instantiation paths.

This route is the runtime-truthful equivalent of `views/chat.py`'s
prior Loop 8.3 placeholder. RBAC: `work_order:create` (Aiden Tier 1
classification is the read-side of the WO submission flow; if the
operator can't create a WO they shouldn't be able to spend tokens
classifying intake either).

Audit:
  - llm.invoked / llm.failed / llm.budget_exceeded emitted by
    invoke_aiden_tier_1 + runtime.budgets — no extra writes here.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

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


router = APIRouter(prefix="/aiden", tags=["aiden"])


class AidenChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class AidenChatResponse(BaseModel):
    ok: bool
    decision_kind: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    work_order_brief: Optional[dict[str, Any]] = None
    workflow_brief: Optional[dict[str, Any]] = None
    clarification: Optional[dict[str, Any]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


def _decision_to_payload(dec) -> dict[str, Any]:  # noqa: ANN001
    """Flatten AidenDecision dataclass → JSON-serialisable dict for the
    response model. dataclasses.asdict already nests sub-dataclasses."""
    return dataclasses.asdict(dec)


@router.post(
    "/chat",
    response_model=AidenChatResponse,
    dependencies=[Depends(require_permission_dep("work_order:create"))],
)
async def aiden_chat(
    body: AidenChatRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> AidenChatResponse:
    try:
        decision = await invoke_aiden_tier_1(
            conn,
            intake_text=body.message,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
        )
    except AidenNoConfig as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_aiden_config", "detail": str(exc)},
        )
    except LlmBudgetExceeded as exc:
        return AidenChatResponse(
            ok=False,
            error=(
                f"llm_budget_exceeded: tenant has used {exc.already_used} "
                f"tokens against ceiling {exc.ceiling}; raise the ceiling "
                f"and retry."
            ),
        )
    except AidenInvocationError as exc:
        return AidenChatResponse(
            ok=False,
            error=f"{exc.kind}: {exc}",
        )

    payload = _decision_to_payload(decision)
    return AidenChatResponse(
        ok=True,
        decision_kind=payload.get("decision_kind"),
        title=payload.get("title"),
        summary=payload.get("summary"),
        work_order_brief=payload.get("work_order_brief"),
        workflow_brief=payload.get("workflow_brief"),
        clarification=payload.get("clarification"),
        provider=payload.get("provider"),
        model=payload.get("model"),
        latency_ms=payload.get("latency_ms"),
    )
