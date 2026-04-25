"""Loop 1 bootstrap + Loop 7 Phase 7.1 hardening — health + readiness.
MegaLoop Beta-1 ε.4 — adds /health/channels + /health/llm so operators
can verify token resolution + per-tenant LLM config liveness without
shelling into env."""

from __future__ import annotations

import os
from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from channel.telegram import env_var_for_telegram_bot_token
from deps import (
    current_user_context,
    get_db_connection,
    get_tenant_scoped_connection,
    require_permission_dep,
)
from llm.credentials import env_var_from_credential_ref

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    database: str


class ChannelHealthRow(BaseModel):
    channel_kind: str
    env_var_name: str
    secret_present: bool
    webhook_secret_present: bool


class ChannelHealthResponse(BaseModel):
    tenant_designation: str
    channels: list[ChannelHealthRow]


class LlmHealthRow(BaseModel):
    agent_role: str
    provider: str
    model: str
    enabled: bool
    credential_state: str  # "set" | "missing" | "malformed"
    env_var_name: Optional[str] = None


class LlmHealthResponse(BaseModel):
    configs: list[LlmHealthRow]
    per_wo_ceiling: int


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok", service="iwo3-api-fastapi", version="0.0.1"
    )


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(
        status="ok", service="iwo3-api-fastapi", version="0.0.1"
    )


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> ReadyResponse:
    row = await conn.fetchrow("SELECT 1 AS ok")
    return ReadyResponse(
        status="ok" if row and row["ok"] == 1 else "error",
        database="connected" if row and row["ok"] == 1 else "unreachable",
    )


@router.get(
    "/health/channels",
    response_model=ChannelHealthResponse,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def health_channels(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ChannelHealthResponse:
    """Beta-1 ε.4 — surface per-channel env-var resolution status for
    the active tenant. No raw secret values; just presence + the env
    var name so operators can verify their config from the browser.

    Currently checks Telegram bot token + Telegram webhook HMAC
    secret (architect Q3 webhook lock). Slack lands in Beta-2;
    its resolver follows the same shape."""
    row = await conn.fetchrow(
        "SELECT designation FROM clients WHERE id = $1::uuid",
        ctx["client_id"],
    )
    designation = row["designation"] if row else ""

    tg_token_var = env_var_for_telegram_bot_token(designation)
    tg_webhook_var = "IWO3_WEBHOOK_HMAC_" + (
        tg_token_var[len("TELEGRAM_BOT_TOKEN_"):]
        if tg_token_var.startswith("TELEGRAM_BOT_TOKEN_")
        else tg_token_var
    )

    return ChannelHealthResponse(
        tenant_designation=designation,
        channels=[
            ChannelHealthRow(
                channel_kind="telegram",
                env_var_name=tg_token_var,
                secret_present=bool(os.environ.get(tg_token_var)),
                webhook_secret_present=bool(os.environ.get(tg_webhook_var)),
            ),
        ],
    )


@router.get(
    "/health/llm",
    response_model=LlmHealthResponse,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def health_llm(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> LlmHealthResponse:
    """Beta-1 ε.4 — per-LLM-config credential resolution + per-tenant
    ceiling visibility. Mirrors the credential-state chip from
    /llm/configs but rolled up to a single health probe."""
    rows = await conn.fetch(
        """
        SELECT agent_role,
               provider,
               model,
               enabled,
               credential_ref
          FROM llm_configs
         WHERE client_id = $1
         ORDER BY agent_role
        """,
        ctx["client_id"],
    )
    ceiling = await conn.fetchval(
        "SELECT llm_per_wo_ceiling FROM clients WHERE id = $1::uuid",
        ctx["client_id"],
    )
    # Default to platform DEFAULT_PER_WO_CEILING when NULL.
    from runtime.budgets import DEFAULT_PER_WO_CEILING

    out: list[LlmHealthRow] = []
    for r in rows:
        env_name = env_var_from_credential_ref(r["credential_ref"] or "")
        if env_name is None:
            state = "malformed"
        elif os.environ.get(env_name):
            state = "set"
        else:
            state = "missing"
        out.append(
            LlmHealthRow(
                agent_role=r["agent_role"],
                provider=r["provider"],
                model=r["model"],
                enabled=r["enabled"],
                credential_state=state,
                env_var_name=env_name,
            )
        )
    return LlmHealthResponse(
        configs=out,
        per_wo_ceiling=int(ceiling) if ceiling is not None else DEFAULT_PER_WO_CEILING,
    )
