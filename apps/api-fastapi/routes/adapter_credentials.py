"""Loop 9 Phase 9.1 + 9.5 — adapter credential + status routes.

POST /adapter_credentials/{id}/confirm_first_invocation
  Phase 9.1. Gated by adapter_credential:rotate (admin-only per Loop 4).
  Idempotent: setting first_invocation_confirmed_at twice is a no-op
  and returns the existing state without writing a second audit row.

GET /adapter_status/{adapter_key}
  Phase 9.5 (scope §3.5). Returns the 4-state Design Lab status for
  the active tenant: live_confirmed | pending_confirmation | disabled
  | credential_missing. Gated by client:read.

Candidate-review is deliberately NOT used for outbound-service
authorization — it governs artifact choice only (Darrel §Q1 lockdown).
"""

from __future__ import annotations

import os
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


# ──────────────────────────────────────────────────────────────────────
# Loop 9 Phase 9.5 — adapter status (Design Lab wiring)
# ──────────────────────────────────────────────────────────────────────


status_router = APIRouter(prefix="/adapter_status", tags=["adapter_status"])


# Per-adapter env flag names (mirror AdapterDescription.envFlagName in TS).
# Add live adapters here as they ship. Sandbox PPTX/PDF (Loop 10) will
# register via the same map.
ADAPTER_ENV_FLAGS = {
    "gamma": "GAMMA_LIVE_ENABLED",
}


class AdapterStatusResponse(BaseModel):
    adapter_key: str
    status: str  # live_confirmed | pending_confirmation | disabled | credential_missing
    env_flag_name: Optional[str] = None
    env_flag_enabled: bool
    credential_id: Optional[str] = None
    credential_ref: Optional[str] = None
    first_invocation_confirmed_at: Optional[str] = None
    notes: Optional[str] = None


@status_router.get(
    "/{adapter_key}",
    response_model=AdapterStatusResponse,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def get_adapter_status(
    adapter_key: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> AdapterStatusResponse:
    """Design Lab-facing live status per (tenant, adapter).

    4-state resolution (Darrel §Q1 dual gate):
      live_confirmed          env flag true AND credential row exists
                              AND first_invocation_confirmed_at not null
      pending_confirmation    env flag true AND credential row exists
                              AND first_invocation_confirmed_at null
      credential_missing      credential row absent for this tenant
      disabled                env flag unset / false (regardless of DB)

    env_flag_name is null for adapters without a live gate (not in
    ADAPTER_ENV_FLAGS). Those are reported as live_confirmed when a
    credential row exists — Sandbox PPTX/PDF (Loop 10) may land this way.
    """
    env_flag_name = ADAPTER_ENV_FLAGS.get(adapter_key)
    env_flag_value = os.environ.get(env_flag_name or "", "")
    env_enabled = env_flag_value == "true"

    row = await conn.fetchrow(
        """
        SELECT ac.id::text                                    AS id,
               ac.credential_ref,
               ac.first_invocation_confirmed_at::text          AS confirmed_at,
               ac.notes                                        AS notes
          FROM adapter_credentials ac
          JOIN adapter_catalog cat ON cat.id = ac.adapter_catalog_id
         WHERE ac.client_id = $1 AND cat.adapter_key = $2
         ORDER BY ac.created_at DESC
         LIMIT 1
        """,
        ctx["client_id"],
        adapter_key,
    )

    if env_flag_name and not env_enabled:
        return AdapterStatusResponse(
            adapter_key=adapter_key,
            status="disabled",
            env_flag_name=env_flag_name,
            env_flag_enabled=False,
            credential_id=row["id"] if row else None,
            credential_ref=row["credential_ref"] if row else None,
            first_invocation_confirmed_at=(
                row["confirmed_at"] if row else None
            ),
            notes=row["notes"] if row else None,
        )

    if row is None:
        return AdapterStatusResponse(
            adapter_key=adapter_key,
            status="credential_missing",
            env_flag_name=env_flag_name,
            env_flag_enabled=env_enabled,
        )

    if env_flag_name and row["confirmed_at"] is None:
        return AdapterStatusResponse(
            adapter_key=adapter_key,
            status="pending_confirmation",
            env_flag_name=env_flag_name,
            env_flag_enabled=env_enabled,
            credential_id=row["id"],
            credential_ref=row["credential_ref"],
            first_invocation_confirmed_at=None,
            notes=row["notes"],
        )

    return AdapterStatusResponse(
        adapter_key=adapter_key,
        status="live_confirmed",
        env_flag_name=env_flag_name,
        env_flag_enabled=env_enabled,
        credential_id=row["id"],
        credential_ref=row["credential_ref"],
        first_invocation_confirmed_at=row["confirmed_at"],
        notes=row["notes"],
    )
