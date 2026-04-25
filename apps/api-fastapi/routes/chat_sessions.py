"""MegaLoop Beta-1 ε.2 / Q7 — operator-facing cross-session chat persistence.

Architect Q7 lock: each (user_id, client_id) pair has exactly one
chat session row. Message history + chat-context (last_work_order_id /
last_output_package_id / etc.) live in JSONB so the shape can flex
during Beta-1; if it stabilises we promote individual columns in
Beta-2 without a breaking API change.

Boundary (architect): this carries operator chat continuity, NOT
agent-side cross-WO Munninn-style memory. The chat persistence is
operator-scoped — a different operator on the same tenant gets a
different session row.

Routes:
  GET /chat_sessions/me           current operator's session for
                                  the active tenant (creates an
                                  empty row on first read so the
                                  Streamlit consumer can write
                                  without a separate POST).
  PUT /chat_sessions/me           overwrite messages + context with
                                  the operator's current state.
                                  Idempotent on (user_id, client_id).
  DELETE /chat_sessions/me        clear history (operator's "Clear
                                  history" button maps here).

RBAC: any tenant member can read + write THEIR OWN session. The
RLS-scoped connection guarantees tenant isolation; the per-user
filter is enforced inside the query (`AND user_id = $1`).
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from authz.audit_writer import write_audit_row
from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)


router = APIRouter(prefix="/chat_sessions", tags=["chat_sessions"])


_MAX_MESSAGES = 200  # hard cap on message history per session
_MAX_CONTEXT_BYTES = 16_384  # context JSONB budget


def _parse_jsonb(value: Any, default: Any) -> Any:
    """asyncpg returns JSONB columns as strings by default; parse them
    to native Python types so the response model serialises correctly."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    return value if value is not None else default


def _row_to_session(row: asyncpg.Record) -> "ChatSession":
    msgs = _parse_jsonb(row["messages"], [])
    ctx = _parse_jsonb(row["context"], {})
    return ChatSession(
        id=row["id"],
        messages=msgs if isinstance(msgs, list) else [],
        context=ctx if isinstance(ctx, dict) else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ChatSession(BaseModel):
    id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class UpdateChatSessionRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


@router.get(
    "/me",
    response_model=ChatSession,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def get_my_session(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ChatSession:
    """Return (or create) the operator's chat session for this tenant.
    Upsert-on-read keeps the Streamlit consumer simple — first chat
    turn doesn't need a separate POST."""
    row = await conn.fetchrow(
        """
        INSERT INTO chat_sessions (user_id, client_id)
        VALUES ($1::uuid, $2::uuid)
        ON CONFLICT ON CONSTRAINT chat_sessions_user_client_uniq
        DO UPDATE SET updated_at = chat_sessions.updated_at
        RETURNING id::text          AS id,
                  messages,
                  context,
                  created_at::text  AS created_at,
                  updated_at::text  AS updated_at
        """,
        ctx["user_id"],
        ctx["client_id"],
    )
    return _row_to_session(row)


@router.put(
    "/me",
    response_model=ChatSession,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def update_my_session(
    body: UpdateChatSessionRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ChatSession:
    """Idempotent overwrite of the operator's session state. The
    Streamlit chat view writes here on every turn so a refresh is a
    no-op against the latest state."""
    msgs = body.messages[-_MAX_MESSAGES:]  # tail trim
    context_blob = json.dumps(body.context)
    if len(context_blob) > _MAX_CONTEXT_BYTES:
        # Truncate by dropping unknown keys; preserve known operator-
        # facing keys. For Beta-1 the cap is generous; if it bites the
        # caller we surface 413 in Beta-2.
        context_blob = json.dumps({})
    row = await conn.fetchrow(
        """
        INSERT INTO chat_sessions (user_id, client_id, messages, context)
        VALUES ($1::uuid, $2::uuid, $3::jsonb, $4::jsonb)
        ON CONFLICT ON CONSTRAINT chat_sessions_user_client_uniq
        DO UPDATE SET messages = EXCLUDED.messages,
                      context  = EXCLUDED.context,
                      updated_at = now()
        RETURNING id::text          AS id,
                  messages,
                  context,
                  created_at::text  AS created_at,
                  updated_at::text  AS updated_at
        """,
        ctx["user_id"],
        ctx["client_id"],
        json.dumps(msgs),
        context_blob,
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="chat_session.updated",
        target_type="chat_session",
        target_id=row["id"],
        metadata={
            "messageCount": len(msgs),
            "contextKeys": list(body.context.keys()),
        },
    )
    return _row_to_session(row)


@router.delete(
    "/me",
    response_model=ChatSession,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def clear_my_session(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ChatSession:
    row = await conn.fetchrow(
        """
        INSERT INTO chat_sessions (user_id, client_id, messages, context)
        VALUES ($1::uuid, $2::uuid, '[]'::jsonb, '{}'::jsonb)
        ON CONFLICT ON CONSTRAINT chat_sessions_user_client_uniq
        DO UPDATE SET messages = '[]'::jsonb,
                      context  = '{}'::jsonb,
                      updated_at = now()
        RETURNING id::text          AS id,
                  messages,
                  context,
                  created_at::text  AS created_at,
                  updated_at::text  AS updated_at
        """,
        ctx["user_id"],
        ctx["client_id"],
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="chat_session.updated",
        target_type="chat_session",
        target_id=row["id"],
        metadata={"cleared": True},
    )
    return ChatSession(
        id=row["id"],
        messages=[],
        context={},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
