"""Loop 7 Phase 7.3 — candidate review routes.

POST /output_handoffs/{id}/select_candidate  body: {reason?}
POST /output_handoffs/{id}/reject_candidate  body: {reason?}

Permission gates are enforced inside the helper
(output_candidate:select / output_candidate:reject).
"""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from deps import current_user_context, get_tenant_scoped_connection
from wo_wf.candidate_review import (
    CandidateHandoffNotFound,
    CandidateNotEligible,
    reject_candidate,
    select_candidate,
)
from wo_wf.transitions import PermissionDenied

router = APIRouter(tags=["candidate_review"])


class CandidateReviewRequest(BaseModel):
    reason: Optional[str] = None


class SelectCandidateResponse(BaseModel):
    selected_handoff_id: str
    rejected_sibling_ids: list[str]
    package_validated: Optional[str] = None


class RejectCandidateResponse(BaseModel):
    rejected_handoff_id: str


def _handle_errors(err: Exception, handoff_id: str) -> HTTPException:
    if isinstance(err, PermissionDenied):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "permission_denied",
                "permission": err.permission,
                "reason": err.reason,
                "role": err.role,
            },
        )
    if isinstance(err, CandidateNotEligible):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "candidate_not_eligible",
                "handoff_id": err.handoff_id,
                "current_status": err.current_status,
            },
        )
    if isinstance(err, CandidateHandoffNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "handoff_id": handoff_id},
        )
    raise err


@router.post(
    "/output_handoffs/{handoff_id}/select_candidate",
    response_model=SelectCandidateResponse,
)
async def select_candidate_route(
    handoff_id: str,
    body: CandidateReviewRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> SelectCandidateResponse:
    try:
        result = await select_candidate(
            conn,
            handoff_id=handoff_id,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            reason=body.reason,
        )
    except (PermissionDenied, CandidateNotEligible, CandidateHandoffNotFound) as err:
        raise _handle_errors(err, handoff_id)
    return SelectCandidateResponse(**result)


@router.post(
    "/output_handoffs/{handoff_id}/reject_candidate",
    response_model=RejectCandidateResponse,
)
async def reject_candidate_route(
    handoff_id: str,
    body: CandidateReviewRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> RejectCandidateResponse:
    try:
        result = await reject_candidate(
            conn,
            handoff_id=handoff_id,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            reason=body.reason,
        )
    except (PermissionDenied, CandidateNotEligible, CandidateHandoffNotFound) as err:
        raise _handle_errors(err, handoff_id)
    return RejectCandidateResponse(**result)


# ──────────────────────────────────────────────────────────────────────
# Loop 9 Phase 9.4 — async polling
# ──────────────────────────────────────────────────────────────────────


from deps import require_permission_dep  # noqa: E402 — grouped for Phase 9.4
from adapter.gamma_poll import poll_gamma_handoff  # noqa: E402


class PollHandoffRequest(BaseModel):
    force_stale_watchdog: bool = False


class PollHandoffResponseModel(BaseModel):
    status: str
    handoff_id: str
    detail: Optional[str] = None
    poll_count: Optional[int] = None
    external_reference: Optional[str] = None
    result_payload_ref: Optional[str] = None
    elapsed_seconds: Optional[int] = None
    current_status: Optional[str] = None


@router.post(
    "/output_handoffs/{handoff_id}/poll",
    response_model=PollHandoffResponseModel,
    dependencies=[Depends(require_permission_dep("output_package:submit"))],
)
async def poll_handoff_route(
    handoff_id: str,
    body: PollHandoffRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> PollHandoffResponseModel:
    """Advance one handoff's polling lifecycle (Phase 9.4 scope §3.4).

    Non-404 outcomes return 200 with a typed `status` field so callers
    (Streamlit Design Lab, scheduled poll jobs) can react without
    special-casing HTTP codes. `handoff_not_found` is the one 404.
    """
    outcome = await poll_gamma_handoff(
        conn,
        handoff_id=handoff_id,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        force_stale_watchdog=body.force_stale_watchdog,
    )
    if outcome.kind == "handoff_not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "handoff_id": handoff_id},
        )
    return PollHandoffResponseModel(
        status=outcome.kind,
        handoff_id=outcome.handoff_id,
        detail=outcome.detail,
        poll_count=outcome.poll_count,
        external_reference=outcome.external_reference,
        result_payload_ref=outcome.result_payload_ref,
        elapsed_seconds=outcome.elapsed_seconds,
        current_status=outcome.current_status,
    )
