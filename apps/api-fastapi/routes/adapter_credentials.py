"""Loop 9 Phase 9.1 — adapter credential administration routes.

POST /adapter_credentials/{id}/confirm_first_invocation
  Body: {notes?: str}
  Permission: adapter_credential:rotate (admin-only per Loop 4).
  Idempotent: setting first_invocation_confirmed_at twice is a no-op
  and returns the existing state without writing a second audit row.

This route is the operator control for the primary leg of the dual
first-live-invocation gate (IWO3_LOOP_8_3_CODEX_DECISIONS §Q1). The
secondary leg is the env flag GAMMA_LIVE_ENABLED (or adapter-specific
equivalent), read inside the dispatcher.

Candidate-review is deliberately NOT used here — candidate-review
governs artifact choice, not outbound-service authorization.
"""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from authz.audit_writer import write_audit_row
from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)

router = APIRouter(prefix="/adapter_credentials", tags=["adapter_credentials"])


class ConfirmFirstInvocationRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=1000)


class AdapterCredentialConfirmResponse(BaseModel):
    id: str
    adapter_key: str
    first_invocation_confirmed_at: str
    first_invocation_confirmed_by_user_id: str
    already_confirmed: bool
    notes: Optional[str] = None


@router.post(
    "/{credential_id}/confirm_first_invocation",
    response_model=AdapterCredentialConfirmResponse,
    dependencies=[Depends(require_permission_dep("adapter_credential:rotate"))],
)
async def confirm_first_invocation(
    credential_id: str,
    body: ConfirmFirstInvocationRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> AdapterCredentialConfirmResponse:
    # Tenant-scoped read (RLS filters cross-tenant rows; the app-layer
    # predicate below is the Phase 4.4 lint-rule belt alongside the RLS
    # suspenders).
    row = await conn.fetchrow(
        """
        SELECT ac.id::text                                   AS id,
               ac.first_invocation_confirmed_at::text        AS prev_confirmed_at,
               ac.first_invocation_confirmed_by_user_id::text AS prev_confirmed_by,
               ac.notes                                      AS prev_notes,
               cat.adapter_key                               AS adapter_key
          FROM adapter_credentials ac
          JOIN adapter_catalog cat ON cat.id = ac.adapter_catalog_id
         WHERE ac.id = $1 AND ac.client_id = $2
        """,
        credential_id,
        ctx["client_id"],
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "not_found",
                "credential_id": credential_id,
            },
        )

    # Idempotent short-circuit — second confirm is a no-op (no new audit
    # row, no DB write). Returns the existing state with already_confirmed=True.
    if row["prev_confirmed_at"] is not None:
        return AdapterCredentialConfirmResponse(
            id=row["id"],
            adapter_key=row["adapter_key"],
            first_invocation_confirmed_at=row["prev_confirmed_at"],
            first_invocation_confirmed_by_user_id=row["prev_confirmed_by"]
            or "",
            already_confirmed=True,
            notes=row["prev_notes"],
        )

    # First confirmation — UPDATE + audit write in the same transaction.
    updated = await conn.fetchrow(
        """
        UPDATE adapter_credentials
           SET first_invocation_confirmed_at       = now(),
               first_invocation_confirmed_by_user_id = $3::uuid,
               notes                               = COALESCE($4, notes),
               updated_at                          = now()
         WHERE id = $1 AND client_id = $2
         RETURNING id::text                              AS id,
                   first_invocation_confirmed_at::text   AS confirmed_at,
                   first_invocation_confirmed_by_user_id::text
                                                         AS confirmed_by,
                   notes                                 AS notes
        """,
        credential_id,
        ctx["client_id"],
        ctx["user_id"],
        body.notes,
    )

    if updated is None:
        # Raced with a concurrent rotation/revocation; surface as 409.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "update_lost",
                "credential_id": credential_id,
            },
        )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="adapter_credential.first_invocation_confirmed",
        target_type="adapter_credential",
        target_id=credential_id,
        metadata={
            "adapter_key": row["adapter_key"],
            "notes_set": body.notes is not None,
        },
    )

    return AdapterCredentialConfirmResponse(
        id=updated["id"],
        adapter_key=row["adapter_key"],
        first_invocation_confirmed_at=updated["confirmed_at"],
        first_invocation_confirmed_by_user_id=updated["confirmed_by"] or "",
        already_confirmed=False,
        notes=updated["notes"],
    )
