"""MegaLoop Alpha α.6 — channel routes (auth-code issuance + identities).

  POST /channel/auth_codes        Operator-issued one-time /start binding code.
                                  Required to bring up a Telegram chat against
                                  this tenant per Stage A § B7.
  GET  /channel/identities        List bound channel identities for the tenant.
  POST /channel/identities/{id}/revoke
                                  Revoke a binding so it can no longer act on
                                  this tenant.

RBAC (per migration 0011_alpha_phase_6_channel_permissions.sql):
  - channel_auth_code:issue     → owner / admin / operator
  - channel_identity:read       → owner / admin / operator / reviewer / agent_system
  - channel_identity:revoke     → owner / admin

Audit:
  - channel_auth_code.issued    written by channel.core.issue_auth_code
  - channel_identity.revoked    written here on the revoke path
"""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from authz.audit_writer import write_audit_row
from channel.core import (
    DEFAULT_AUTH_CODE_TTL_MINUTES,
    issue_auth_code,
)
from contracts.enums import CHANNEL_KIND
from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)


router = APIRouter(prefix="/channel", tags=["channel"])


# ── POST /channel/auth_codes ──────────────────────────────────────────


class IssueAuthCodeRequest(BaseModel):
    channel_kind: str = Field(
        ..., description="One of channel_kind enum (telegram/slack/email/sms)"
    )
    ttl_minutes: int = Field(
        DEFAULT_AUTH_CODE_TTL_MINUTES,
        ge=1,
        le=1440,
        description="Time-to-live in minutes (1..1440). Default 15.",
    )


class IssueAuthCodeResponse(BaseModel):
    id: str
    code: str
    channel_kind: str
    expires_at: str
    instructions: str = Field(
        ...,
        description="Plain-text instructions to forward to the chat operator.",
    )


@router.post(
    "/auth_codes",
    response_model=IssueAuthCodeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission_dep("channel_auth_code:issue"))],
)
async def issue_channel_auth_code(
    body: IssueAuthCodeRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> IssueAuthCodeResponse:
    if body.channel_kind not in CHANNEL_KIND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_channel_kind",
                "value": body.channel_kind,
                "allowed": list(CHANNEL_KIND),
            },
        )

    issued = await issue_auth_code(
        conn,
        client_id=ctx["client_id"],
        issued_by_user_id=ctx["user_id"],
        channel_kind=body.channel_kind,
        ttl_minutes=body.ttl_minutes,
    )
    instructions = (
        f"Open a chat with the {body.channel_kind} bot for this tenant and "
        f"send: /start {issued.code}\n"
        f"This code is single-use and expires "
        f"{issued.expires_at.isoformat()}."
    )
    return IssueAuthCodeResponse(
        id=issued.id,
        code=issued.code,
        channel_kind=body.channel_kind,
        expires_at=issued.expires_at.isoformat(),
        instructions=instructions,
    )


# ── GET /channel/identities ───────────────────────────────────────────


class ChannelIdentityListItem(BaseModel):
    id: str
    channel_kind: str
    external_id: str
    user_id: str
    status: str
    bound_at: Optional[str]
    last_seen_at: Optional[str]


class ListChannelIdentitiesResponse(BaseModel):
    identities: list[ChannelIdentityListItem]


@router.get(
    "/identities",
    response_model=ListChannelIdentitiesResponse,
    dependencies=[Depends(require_permission_dep("channel_identity:read"))],
)
async def list_channel_identities(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    channel_kind: Annotated[
        Optional[str],
        Query(description="Filter by channel_kind."),
    ] = None,
    only_active: Annotated[
        bool,
        Query(
            description="When true (default), exclude revoked identities."
        ),
    ] = True,
) -> ListChannelIdentitiesResponse:
    if channel_kind is not None and channel_kind not in CHANNEL_KIND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_channel_kind",
                "value": channel_kind,
                "allowed": list(CHANNEL_KIND),
            },
        )

    where = ["client_id = $1::uuid"]
    args: list = [ctx["client_id"]]
    if channel_kind is not None:
        args.append(channel_kind)
        where.append(f"channel_kind = ${len(args)}::channel_kind")
    if only_active:
        where.append("status = 'active'")
    sql = f"""
        SELECT id::text                AS id,
               channel_kind::text      AS channel_kind,
               external_id,
               user_id::text           AS user_id,
               status::text            AS status,
               bound_at::text          AS bound_at,
               last_seen_at::text      AS last_seen_at
          FROM channel_identities
         WHERE {' AND '.join(where)}
         ORDER BY bound_at DESC
         LIMIT 200
    """
    rows = await conn.fetch(sql, *args)
    return ListChannelIdentitiesResponse(
        identities=[ChannelIdentityListItem(**dict(r)) for r in rows]
    )


# ── POST /channel/identities/{id}/revoke ──────────────────────────────


class RevokeIdentityResponse(BaseModel):
    id: str
    status: str


@router.post(
    "/identities/{identity_id}/revoke",
    response_model=RevokeIdentityResponse,
    dependencies=[Depends(require_permission_dep("channel_identity:revoke"))],
)
async def revoke_channel_identity(
    identity_id: Annotated[str, Path(min_length=1)],
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> RevokeIdentityResponse:
    try:
        row = await conn.fetchrow(
            """
            UPDATE channel_identities
               SET status = 'revoked',
                   revoked_at = now(),
                   updated_at = now()
             WHERE id = $1::uuid
               AND client_id = $2::uuid
               AND status = 'active'
            RETURNING id::text AS id, status::text AS status,
                      channel_kind::text AS channel_kind,
                      external_id
            """,
            identity_id,
            ctx["client_id"],
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_identity_id", "value": identity_id},
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "identity_not_found_or_already_revoked"},
        )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="channel_identity.revoked",
        target_type="channel_identity",
        target_id=row["id"],
        metadata={
            "channelKind": row["channel_kind"],
            "externalId": row["external_id"],
        },
    )
    return RevokeIdentityResponse(id=row["id"], status=row["status"])
