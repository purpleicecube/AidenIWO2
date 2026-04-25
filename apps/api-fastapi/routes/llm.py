"""Loop 9 Phase 9.3 — LLM provider routes.

  GET  /llm/providers           list known providers + Phase-9.3 callable subset
  POST /llm/test                run a tiny chat completion against the
                                tenant's resolved LLM config (no DB writes)
  GET  /llm/configs             list configured (agent_role, provider, model)
                                tuples for the active tenant

`POST /llm/test` is gated by `system:admin` per Loop 4 §Q2 — connection
testing pokes provider endpoints with the runtime credential and is an
admin operation.
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
from llm.config_resolver import resolve_llm_config
from llm.credentials import LlmCredentialError, resolve_credential
from llm.providers import (
    LlmProviderError,
    call_openai_compatible,
    callable_providers,
    known_providers,
)


router = APIRouter(prefix="/llm", tags=["llm"])


class ProviderListItem(BaseModel):
    name: str
    callable_in_phase_9_3: bool


class ListProvidersResponse(BaseModel):
    providers: list[ProviderListItem]


@router.get(
    "/providers",
    response_model=ListProvidersResponse,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def list_providers() -> ListProvidersResponse:
    callable_set = callable_providers()
    providers = [
        ProviderListItem(
            name=name, callable_in_phase_9_3=(name in callable_set)
        )
        for name in known_providers()
    ]
    return ListProvidersResponse(providers=providers)


class ConfigListItem(BaseModel):
    id: str
    agent_role: str
    provider: str
    model: str
    enabled: bool
    has_system_prompt: bool


class ListConfigsResponse(BaseModel):
    configs: list[ConfigListItem]


@router.get(
    "/configs",
    response_model=ListConfigsResponse,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def list_configs(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ListConfigsResponse:
    rows = await conn.fetch(
        """
        SELECT id::text             AS id,
               agent_role,
               provider,
               model,
               enabled,
               (system_prompt IS NOT NULL AND length(system_prompt) > 0)
                                    AS has_system_prompt
          FROM llm_configs
         WHERE client_id = $1
         ORDER BY agent_role
        """,
        ctx["client_id"],
    )
    return ListConfigsResponse(
        configs=[ConfigListItem(**dict(r)) for r in rows]
    )


class LlmTestRequest(BaseModel):
    agent_role: str = Field(..., min_length=1, max_length=64)
    user_message: str = Field("ping", max_length=500)


class LlmTestResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    resolved_role: str
    source: str
    latency_ms: int
    completion_chars: int
    sample: Optional[str] = None
    error: Optional[str] = None


@router.post(
    "/test",
    response_model=LlmTestResponse,
    dependencies=[Depends(require_permission_dep("system:admin"))],
)
async def test_llm(
    body: LlmTestRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> LlmTestResponse:
    cfg = await resolve_llm_config(
        conn, client_id=ctx["client_id"], agent_role=body.agent_role
    )
    if cfg is None:
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="llm.failed",
            target_type="llm_config",
            target_id=None,
            metadata={
                "requested_role": body.agent_role,
                "kind": "no_llm_configured",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_llm_configured",
                "agent_role": body.agent_role,
            },
        )

    if not cfg.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "llm_config_disabled", "config_id": cfg.config_id},
        )

    try:
        api_key = resolve_credential(cfg.credential_ref)
    except LlmCredentialError as exc:
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="llm.failed",
            target_type="llm_config",
            target_id=cfg.config_id,
            metadata={
                "kind": "credential_missing",
                "credential_ref": cfg.credential_ref,
                "detail": str(exc),
            },
        )
        return LlmTestResponse(
            ok=False,
            provider=cfg.provider,
            model=cfg.model,
            resolved_role=cfg.resolved_role,
            source=cfg.source,
            latency_ms=0,
            completion_chars=0,
            error=f"credential_missing: {exc}",
        )

    try:
        result = call_openai_compatible(
            provider=cfg.provider,
            model=cfg.model,
            api_key=api_key,
            base_url=cfg.base_url,
            system_prompt=cfg.system_prompt,
            user_message=body.user_message,
            options=cfg.options,
        )
    except LlmProviderError as exc:
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="llm_provider.connection_tested",
            target_type="llm_config",
            target_id=cfg.config_id,
            metadata={
                "ok": False,
                "provider": cfg.provider,
                "model": cfg.model,
                "kind": exc.kind,
                "http_status": exc.http_status,
            },
        )
        return LlmTestResponse(
            ok=False,
            provider=cfg.provider,
            model=cfg.model,
            resolved_role=cfg.resolved_role,
            source=cfg.source,
            latency_ms=0,
            completion_chars=0,
            error=f"{exc.kind}: {exc}",
        )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_provider.connection_tested",
        target_type="llm_config",
        target_id=cfg.config_id,
        metadata={
            "ok": True,
            "provider": cfg.provider,
            "model": cfg.model,
            "latency_ms": result.latency_ms,
            "prompt_chars": result.prompt_chars,
            "completion_chars": result.completion_chars,
        },
    )
    return LlmTestResponse(
        ok=True,
        provider=cfg.provider,
        model=cfg.model,
        resolved_role=cfg.resolved_role,
        source=cfg.source,
        latency_ms=result.latency_ms,
        completion_chars=result.completion_chars,
        sample=result.text[:200] if result.text else None,
    )
