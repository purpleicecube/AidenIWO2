"""Loop 7 Phase 7.1 — FastAPI dependency providers.

Shared dependency builders that routers consume via FastAPI's
`Depends` system:

  - ``get_db_pool``          process-lifetime asyncpg pool; built on
                             startup, closed on shutdown. Never yields
                             a connection directly; callers ask for
                             ``get_db_connection`` or
                             ``get_tenant_scoped_connection``.
  - ``get_db_connection``    acquires a connection from the pool for
                             the duration of the request. Useful for
                             bypass-path (admin/superuser) queries
                             that should not flow through RLS.
  - ``get_tenant_scoped_connection``  acquires + begins a transaction
                             + SET LOCAL ROLE iwo3_app + SET LOCAL
                             app.current_client_id. The transaction
                             commits when the request handler returns
                             without exception; rolls back on
                             exception. RLS policies (Phase 4.3) fire
                             on every query inside this scope.
  - ``current_user_context`` extracts the dev bearer pair
                             ``X-IWO3-User`` + ``X-IWO3-Client`` from
                             request headers. Production auth
                             (OAuth/SSO) lands in Loop 9+.
  - ``require_permission_dep``  closure factory: ``require_permission_dep("work_order:read")``
                             returns a Depends that fails the request
                             with HTTP 403 + writes an ``authz.denied``
                             audit row when the caller's role lacks
                             the named permission.

Policy invariants (per ADR-014 + ADR-015):
  - No handler ever constructs its own DB connection — every DB
    touch flows through one of the two connection deps above.
  - No handler ever checks permissions manually — every privileged
    mutation depends on ``require_permission_dep(key)``.
  - Dev auth headers must NEVER appear in error responses or server
    logs (D06 mitigation).
"""

from __future__ import annotations

import os
from typing import Annotated, AsyncIterator, Optional

import asyncpg
from fastapi import Depends, Header, HTTPException, Request, status

from authz.audit_writer import write_audit_row
from authz.check_permission import (
    UserGrant,
    check_permission_decide,
)


# --- Process-lifetime pool -----------------------------------------------

_POOL: Optional[asyncpg.Pool] = None


async def startup_db_pool() -> None:
    global _POOL
    url = os.environ.get("IWO3_DATABASE_URL")
    if not url:
        raise RuntimeError("IWO3_DATABASE_URL is required")
    _POOL = await asyncpg.create_pool(dsn=url, min_size=1, max_size=10)


async def shutdown_db_pool() -> None:
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


def get_db_pool() -> asyncpg.Pool:
    if _POOL is None:
        raise RuntimeError(
            "DB pool not initialised; did startup_db_pool run?"
        )
    return _POOL


# --- Connection dependency (bypass path) ---------------------------------


async def get_db_connection() -> AsyncIterator[asyncpg.Connection]:
    """Acquires a connection for the lifetime of the request. Does NOT
    open a transaction and does NOT set the tenant context — handlers
    using this dep run as the `iwo3` superuser and bypass RLS. Use for
    admin-ish reads (e.g. listing tenants the user is a member of, where
    the policy is enforced by explicit WHERE clauses).
    """
    pool = get_db_pool()
    async with pool.acquire() as conn:
        yield conn


# --- Tenant-scoped connection dependency (RLS-enforced path) ------------


async def get_tenant_scoped_connection(
    request: Request,
) -> AsyncIterator[asyncpg.Connection]:
    """Acquires + begins + SET LOCAL ROLE iwo3_app + SET LOCAL
    app.current_client_id. Commits on success, rolls back on exception.
    The tenant context is taken from the current_user_context stashed on
    the request state by the `current_user_context` dep.
    """
    ctx = getattr(request.state, "user_context", None)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user context missing — set X-IWO3-User + X-IWO3-Client",
        )
    pool = get_db_pool()
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            # set_config('app.current_client_id', $1, true) — SET LOCAL
            await conn.execute(
                "SELECT set_config('app.current_client_id', $1, true)",
                ctx["client_id"],
            )
            await conn.execute("SET LOCAL ROLE iwo3_app")
            yield conn
        except Exception:
            await tx.rollback()
            raise
        else:
            await tx.commit()


# --- User context --------------------------------------------------------


def _auth_mode() -> str:
    """Beta-1 ε.3 / Q2 — auth-mode selector.
    `dev_bearer` (legacy / local dev): X-IWO3-User + X-IWO3-Client headers.
    `jwt`        (production): Authorization: Bearer <signed-jwt>.
    Default = `dev_bearer` to preserve all pre-Beta tests + tooling.
    Operator opts into JWT mode via env when production-deploying.
    """
    return os.environ.get("IWO3_AUTH_MODE", "dev_bearer").strip().lower() or "dev_bearer"


async def current_user_context(
    request: Request,
    x_iwo3_user: Annotated[Optional[str], Header(alias="X-IWO3-User")] = None,
    x_iwo3_client: Annotated[
        Optional[str], Header(alias="X-IWO3-Client")
    ] = None,
    authorization: Annotated[Optional[str], Header(alias="Authorization")] = None,
) -> dict:
    """Auth-mode-aware user context resolver.

    `dev_bearer` mode: X-IWO3-User + X-IWO3-Client headers (the
    canonical pre-Beta behaviour).

    `jwt` mode: Authorization: Bearer <signed-jwt>; the header takes
    precedence when both are present so a JWT-authenticated request
    keeps working even if a stale dev header is included.

    Returns ``{"user_id": str, "client_id": str}`` and stashes it on
    ``request.state.user_context`` so tenant-scoped connection deps can
    read it.
    """
    mode = _auth_mode()

    # JWT mode: signed access token via Authorization header.
    if mode == "jwt" or (authorization and authorization.startswith("Bearer ")):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization: Bearer <jwt> header required",
            )
        # Lazy import — auth.jwt_tokens is independent of FastAPI.
        from auth.jwt_tokens import TokenError, decode as jwt_decode

        token = authorization[len("Bearer "):].strip()
        try:
            claims = jwt_decode(token, expected_typ="access")
        except TokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_token", "kind": exc.kind},
            )
        ctx = {"user_id": claims["sub"], "client_id": claims["cid"]}
        request.state.user_context = ctx
        return ctx

    # dev_bearer mode (default): legacy header pair.
    if not x_iwo3_user or not x_iwo3_client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-IWO3-User and X-IWO3-Client headers required (or Authorization: Bearer in jwt mode)",
        )
    ctx = {"user_id": x_iwo3_user, "client_id": x_iwo3_client}
    request.state.user_context = ctx
    return ctx


# --- require_permission Depends factory ---------------------------------


async def _load_permission_ctx(
    conn: asyncpg.Connection, user_id: str, client_id: str, permission: str
) -> dict:
    """Load the decider inputs (role + role_permissions + grants) using
    the bypass connection. We do this outside the tenant-scoped
    transaction so an `authz.denied` row can be written after a deny
    without RLS refusing the write (tenant context is set on the write
    path below).
    """
    vocab = await conn.fetch("SELECT permission_key FROM permissions")
    known = [r["permission_key"] for r in vocab]
    if permission not in known:
        return {"role": None, "role_permissions": [], "user_grants": []}

    mem_rows = await conn.fetch(
        """
        SELECT role::text AS role
        FROM client_memberships
        WHERE user_id = $1 AND client_id = $2 AND status = 'active'
        LIMIT 1
        """,
        user_id,
        client_id,
    )
    if not mem_rows:
        return {"role": None, "role_permissions": [], "user_grants": []}
    role = mem_rows[0]["role"]

    role_perm_rows = await conn.fetch(
        """
        SELECT p.permission_key
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE rp.role = $1::membership_role
        """,
        role,
    )
    role_perms = [r["permission_key"] for r in role_perm_rows]

    grant_rows = await conn.fetch(
        """
        SELECT p.permission_key, pg.grant_type::text AS grant_type
        FROM permission_grants pg
        JOIN permissions p ON p.id = pg.permission_id
        WHERE pg.user_id = $1 AND pg.client_id = $2
        """,
        user_id,
        client_id,
    )
    user_grants = [
        UserGrant(permission_key=r["permission_key"], grant_type=r["grant_type"])
        for r in grant_rows
    ]

    return {
        "role": role,
        "role_permissions": role_perms,
        "user_grants": user_grants,
        "known_permissions": known,
    }


async def _write_authz_denied(
    conn: asyncpg.Connection,
    user_id: str,
    client_id: str,
    permission: str,
    reason: str,
    role: Optional[str],
) -> None:
    """Write an authz.denied audit row via the canonical Python audit
    writer. Uses the bypass connection so the write is not blocked by
    RLS when the caller has no tenant context."""
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=user_id,
        event="authz.denied",
        target_type="permission_check",
        target_id=permission,
        metadata={
            "permission": permission,
            "decision_reason": reason,
            "role": role,
            "emitted_by": "fastapi.require_permission_dep",
        },
    )


def require_permission_dep(permission: str):
    """Returns a FastAPI dependency that fails the request with 403
    when the current user lacks `permission`. Writes an `authz.denied`
    audit row on denial (same semantics as TS `requirePermission`).
    """

    async def _dep(
        ctx: Annotated[dict, Depends(current_user_context)],
        conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
    ) -> dict:
        inputs = await _load_permission_ctx(
            conn, ctx["user_id"], ctx["client_id"], permission
        )
        decision = check_permission_decide(
            role=inputs["role"],
            role_permissions=inputs["role_permissions"],
            user_grants=inputs["user_grants"],
            permission=permission,
            known_permissions=inputs.get("known_permissions"),
        )
        if decision.allowed:
            return ctx
        await _write_authz_denied(
            conn,
            ctx["user_id"],
            ctx["client_id"],
            permission,
            decision.reason,
            decision.role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "permission_denied",
                "permission": permission,
                "reason": decision.reason,
                "role": decision.role,
            },
        )

    return _dep
