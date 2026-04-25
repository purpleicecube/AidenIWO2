"""MegaLoop Beta-1 ε.3 / Q2 — auth routes (signed JWT, stdlib HS256).

  POST /auth/login      {email, password, client_id} → access + refresh
  POST /auth/refresh    {refresh_token} → new access token
  POST /auth/logout     no-op for Beta-1; client discards tokens

Architect Q2 lock: custom signed JWT, self-hosted, no external auth
dependency. Dev bearer stays local-only behind IWO3_AUTH_MODE.

Audit emissions (locked under BETA_PHASE_1_AUDIT_EVENTS in ε.1):
  auth.session_started   on successful login
  auth.session_refreshed on successful refresh
  auth.session_ended     on explicit logout
  auth.login_failed      on bad password or unknown email
"""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth.jwt_tokens import (
    DEFAULT_ACCESS_TTL_SECONDS,
    DEFAULT_REFRESH_TTL_SECONDS,
    TokenError,
    decode as jwt_decode,
    encode as jwt_encode,
)
from auth.passwords import verify_password
from authz.audit_writer import write_audit_row
from deps import get_db_pool


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=512)
    client_id: str = Field(
        ...,
        description="Tenant id the operator wants to log into.",
    )


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_in: int = DEFAULT_ACCESS_TTL_SECONDS
    refresh_expires_in: int = DEFAULT_REFRESH_TTL_SECONDS


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    access_expires_in: int = DEFAULT_ACCESS_TTL_SECONDS


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest) -> TokenPair:
    """Validate (email, password, client_id) and issue a token pair.
    The login route does NOT depend on `current_user_context` — it's
    the bootstrap edge before auth is established."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Bypass connection (no tenant scope yet — we don't know which
        # tenant until the user picks one). RLS on users would block
        # us anyway; the login path is the architectural exception.
        row = await conn.fetchrow(
            """
            SELECT u.id::text          AS user_id,
                   u.password_hash,
                   u.status::text      AS status,
                   m.client_id::text   AS membership_client_id,
                   m.status::text      AS membership_status
              FROM users u
              LEFT JOIN client_memberships m
                ON m.user_id = u.id
               AND m.client_id = $1::uuid
               AND m.status = 'active'
             WHERE lower(u.email) = lower($2)
             LIMIT 1
            """,
            body.client_id,
            body.email,
        )
    if (
        row is None
        or row["password_hash"] is None
        or not verify_password(body.password, row["password_hash"])
        or row["status"] != "active"
        or row["membership_client_id"] is None
    ):
        # Audit the failure under the tenant the operator was trying
        # to enter; write on a tenant-scoped tx.
        await _emit_login_failed(
            client_id=body.client_id,
            email=body.email,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials"},
        )

    access = jwt_encode(
        user_id=row["user_id"],
        client_id=body.client_id,
        typ="access",
    )
    refresh = jwt_encode(
        user_id=row["user_id"],
        client_id=body.client_id,
        typ="refresh",
    )
    await _emit_session_started(
        user_id=row["user_id"], client_id=body.client_id
    )
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=AccessToken)
async def refresh(body: RefreshRequest) -> AccessToken:
    try:
        claims = jwt_decode(body.refresh_token, expected_typ="refresh")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_refresh", "kind": exc.kind},
        )
    access = jwt_encode(
        user_id=claims["sub"],
        client_id=claims["cid"],
        typ="access",
    )
    await _emit_session_refreshed(
        user_id=claims["sub"], client_id=claims["cid"]
    )
    return AccessToken(access_token=access)


@router.post("/logout", response_model=dict)
async def logout(
    body: Optional[RefreshRequest] = None,
) -> dict:
    """No-op for Beta-1: tokens are stateless; client discards.
    Beta-1.5 may add a JTI revocation list. We emit the audit row so
    operators can correlate logout intent."""
    if body and body.refresh_token:
        try:
            claims = jwt_decode(body.refresh_token, expected_typ="refresh")
            await _emit_session_ended(
                user_id=claims["sub"], client_id=claims["cid"]
            )
        except TokenError:
            pass
    return {"ok": True}


# ── audit helpers (no current_user_context — login is bootstrap) ──────


async def _open_tenant_scope(conn: asyncpg.Connection, client_id: str) -> None:
    await conn.execute(
        "SELECT set_config('app.current_client_id', $1, true)", client_id
    )
    await conn.execute("SET LOCAL ROLE iwo3_app")


async def _emit_login_failed(*, client_id: str, email: str) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                await _open_tenant_scope(conn, client_id)
                await write_audit_row(
                    conn,
                    client_id=client_id,
                    actor_user_id=None,
                    event="auth.login_failed",
                    target_type="user",
                    target_id=None,
                    metadata={"email": email[:64], "reason": "invalid_credentials"},
                )
        except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
            # Bad client_id → don't audit; the route already 401ed.
            pass


async def _emit_session_started(*, user_id: str, client_id: str) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _open_tenant_scope(conn, client_id)
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=user_id,
                event="auth.session_started",
                target_type="user",
                target_id=user_id,
                metadata={},
            )


async def _emit_session_refreshed(*, user_id: str, client_id: str) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _open_tenant_scope(conn, client_id)
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=user_id,
                event="auth.session_refreshed",
                target_type="user",
                target_id=user_id,
                metadata={},
            )


async def _emit_session_ended(*, user_id: str, client_id: str) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _open_tenant_scope(conn, client_id)
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=user_id,
                event="auth.session_ended",
                target_type="user",
                target_id=user_id,
                metadata={},
            )
