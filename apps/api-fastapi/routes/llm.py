"""Loop 9 Phase 9.3 — LLM provider routes.
Pre-Beta β.2 — CRUD parity v1 for llm_configs (admin-gated).

  GET    /llm/providers           list known providers + callable subset
  POST   /llm/test                connection test (admin)
  GET    /llm/configs             list per-tenant configs (sanitised)
  POST   /llm/configs             create a new config row (admin)
  PATCH  /llm/configs/{id}        partial update (admin)
  DELETE /llm/configs/{id}        soft delete via enabled=false (admin);
                                  ?hard=true for full row removal

All write paths are gated by `system:admin` per Loop 4 §Q2 + Pre-Beta
β.2 acceptance — credential edits + provider/model swaps are admin
operations. Audit emissions:
  llm_config.created   on POST
  llm_config.updated   on PATCH (any field except enabled→false)
  llm_config.disabled  on PATCH (enabled→false) or DELETE (soft)

Raw API keys never appear in the response. The list/get response
includes a credential-state chip:
  {credential_state: "set" | "missing" | "malformed",
   env_var_name: "GROQ_API_KEY" | null}
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Optional

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
from llm.credentials import (
    LlmCredentialError,
    env_var_from_credential_ref,
    resolve_credential,
)
from llm.providers import (
    LlmProviderError,
    call_openai_compatible,
    callable_providers,
    known_providers,
)


def _credential_state_for_ref(ref: Optional[str]) -> tuple[str, Optional[str]]:
    """Return (state, env_var_name) for a credential_ref. State is
    "set" | "missing" | "malformed". Never returns the raw secret."""
    if not ref:
        return ("malformed", None)
    name = env_var_from_credential_ref(ref)
    if not name:
        return ("malformed", None)
    import os as _os  # local import to keep the credential helpers tight
    return ("set" if _os.environ.get(name) else "missing"), name


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
    display_name: str
    description: Optional[str] = None
    provider: str
    model: str
    base_url: Optional[str] = None
    enabled: bool
    has_system_prompt: bool
    credential_state: str  # "set" | "missing" | "malformed"
    env_var_name: Optional[str] = None


class ListConfigsResponse(BaseModel):
    configs: list[ConfigListItem]


def _row_to_list_item(row: asyncpg.Record) -> ConfigListItem:
    state, env_name = _credential_state_for_ref(row["credential_ref"])
    return ConfigListItem(
        id=row["id"],
        agent_role=row["agent_role"],
        display_name=row["display_name"],
        description=row["description"],
        provider=row["provider"],
        model=row["model"],
        base_url=row["base_url"],
        enabled=row["enabled"],
        has_system_prompt=row["has_system_prompt"],
        credential_state=state,
        env_var_name=env_name,
    )


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
               display_name,
               description,
               provider,
               model,
               base_url,
               credential_ref,
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
        configs=[_row_to_list_item(r) for r in rows]
    )


# ── CRUD (Pre-Beta β.2) ───────────────────────────────────────────────


_VALID_AGENT_ROLE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
_CREDENTIAL_REF = re.compile(r"^credential_ref:env:[A-Za-z0-9_]+$")


class CreateLlmConfigRequest(BaseModel):
    agent_role: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    provider: str = Field(..., min_length=1, max_length=32)
    model: str = Field(..., min_length=1, max_length=128)
    base_url: Optional[str] = Field(None, max_length=256)
    credential_ref: str = Field(..., min_length=1, max_length=256)
    system_prompt: Optional[str] = None
    options: Optional[dict[str, Any]] = None
    enabled: bool = True


class UpdateLlmConfigRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    provider: Optional[str] = Field(None, min_length=1, max_length=32)
    model: Optional[str] = Field(None, min_length=1, max_length=128)
    base_url: Optional[str] = Field(None, max_length=256)
    credential_ref: Optional[str] = Field(None, min_length=1, max_length=256)
    system_prompt: Optional[str] = None
    options: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None


class LlmConfigResponse(BaseModel):
    config: ConfigListItem


def _validate_agent_role(role: str) -> None:
    if not _VALID_AGENT_ROLE.match(role):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_agent_role",
                "value": role,
                "expected_pattern": _VALID_AGENT_ROLE.pattern,
            },
        )


def _validate_credential_ref(ref: str) -> None:
    if not _CREDENTIAL_REF.match(ref):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_credential_ref",
                "value": ref,
                "expected_pattern": _CREDENTIAL_REF.pattern,
            },
        )


def _validate_provider(provider: str) -> None:
    if provider not in known_providers():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_provider",
                "value": provider,
                "allowed": list(known_providers()),
            },
        )


@router.post(
    "/configs",
    response_model=LlmConfigResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission_dep("llm_config:write"))],
)
async def create_config(
    body: CreateLlmConfigRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> LlmConfigResponse:
    _validate_agent_role(body.agent_role)
    _validate_credential_ref(body.credential_ref)
    _validate_provider(body.provider)

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO llm_configs
              (client_id, agent_role, display_name, description,
               provider, model, base_url, credential_ref, system_prompt,
               options, enabled)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9,
                    $10::jsonb, $11)
            RETURNING id::text             AS id,
                      agent_role,
                      display_name,
                      description,
                      provider,
                      model,
                      base_url,
                      credential_ref,
                      enabled,
                      (system_prompt IS NOT NULL
                        AND length(system_prompt) > 0) AS has_system_prompt
            """,
            ctx["client_id"],
            body.agent_role,
            body.display_name,
            body.description,
            body.provider,
            body.model,
            body.base_url,
            body.credential_ref,
            body.system_prompt,
            json.dumps(body.options) if body.options is not None else None,
            body.enabled,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "agent_role_already_exists",
                "agent_role": body.agent_role,
            },
        )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_config.created",
        target_type="llm_config",
        target_id=row["id"],
        metadata={
            "agentRole": body.agent_role,
            "provider": body.provider,
            "model": body.model,
            "enabled": body.enabled,
        },
    )
    return LlmConfigResponse(config=_row_to_list_item(row))


@router.patch(
    "/configs/{config_id}",
    response_model=LlmConfigResponse,
    dependencies=[Depends(require_permission_dep("llm_config:write"))],
)
async def update_config(
    config_id: str,
    body: UpdateLlmConfigRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> LlmConfigResponse:
    if body.credential_ref is not None:
        _validate_credential_ref(body.credential_ref)
    if body.provider is not None:
        _validate_provider(body.provider)

    sets: list[str] = []
    args: list[Any] = []
    field_map: dict[str, Any] = {}

    def _add(field: str, sql_expr: str, value: Any) -> None:
        args.append(value)
        sets.append(f"{field} = {sql_expr.format(idx=len(args))}")
        field_map[field] = value

    if body.display_name is not None:
        _add("display_name", "${idx}", body.display_name)
    if body.description is not None:
        _add("description", "${idx}", body.description)
    if body.provider is not None:
        _add("provider", "${idx}", body.provider)
    if body.model is not None:
        _add("model", "${idx}", body.model)
    if body.base_url is not None:
        _add("base_url", "${idx}", body.base_url)
    if body.credential_ref is not None:
        _add("credential_ref", "${idx}", body.credential_ref)
    if body.system_prompt is not None:
        _add("system_prompt", "${idx}", body.system_prompt)
    if body.options is not None:
        _add("options", "${idx}::jsonb", json.dumps(body.options))
    if body.enabled is not None:
        _add("enabled", "${idx}", body.enabled)

    if not sets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_fields_to_update"},
        )

    sets.append("updated_at = now()")
    args.append(config_id)
    args.append(ctx["client_id"])

    sql = f"""
        UPDATE llm_configs
           SET {', '.join(sets)}
         WHERE id = ${len(args) - 1}::uuid
           AND client_id = ${len(args)}::uuid
        RETURNING id::text             AS id,
                  agent_role,
                  display_name,
                  description,
                  provider,
                  model,
                  base_url,
                  credential_ref,
                  enabled,
                  (system_prompt IS NOT NULL
                    AND length(system_prompt) > 0) AS has_system_prompt
    """
    try:
        row = await conn.fetchrow(sql, *args)
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_config_id", "value": config_id},
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "config_not_found", "id": config_id},
        )

    # Distinguish "disabled" event from a generic update so audit
    # forensics can answer "who turned it off" without parsing diffs.
    is_disable_event = (
        body.enabled is False
        and len([k for k in field_map if k != "enabled"]) == 0
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_config.disabled" if is_disable_event else "llm_config.updated",
        target_type="llm_config",
        target_id=row["id"],
        metadata={
            "agentRole": row["agent_role"],
            "fieldsChanged": list(field_map.keys()),
        },
    )
    return LlmConfigResponse(config=_row_to_list_item(row))


@router.delete(
    "/configs/{config_id}",
    response_model=LlmConfigResponse,
    dependencies=[Depends(require_permission_dep("llm_config:delete"))],
)
async def delete_config(
    config_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    hard: bool = False,
) -> LlmConfigResponse:
    """Soft delete (default) sets enabled=false; hard=true removes the
    row. Soft delete is the default because removing the
    `aiden_tier_1` row would break Tier 1 fallback for the tenant; the
    operator must explicitly opt into a hard delete."""
    if hard:
        try:
            row = await conn.fetchrow(
                """
                DELETE FROM llm_configs
                 WHERE id = $1::uuid AND client_id = $2::uuid
                RETURNING id::text             AS id,
                          agent_role,
                          display_name,
                          description,
                          provider,
                          model,
                          base_url,
                          credential_ref,
                          enabled,
                          false AS has_system_prompt
                """,
                config_id,
                ctx["client_id"],
            )
        except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_config_id", "value": config_id},
            )
    else:
        try:
            row = await conn.fetchrow(
                """
                UPDATE llm_configs
                   SET enabled = false, updated_at = now()
                 WHERE id = $1::uuid AND client_id = $2::uuid
                RETURNING id::text             AS id,
                          agent_role,
                          display_name,
                          description,
                          provider,
                          model,
                          base_url,
                          credential_ref,
                          enabled,
                          (system_prompt IS NOT NULL
                            AND length(system_prompt) > 0) AS has_system_prompt
                """,
                config_id,
                ctx["client_id"],
            )
        except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_config_id", "value": config_id},
            )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "config_not_found", "id": config_id},
        )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_config.disabled",
        target_type="llm_config",
        target_id=row["id"],
        metadata={
            "agentRole": row["agent_role"],
            "hardDelete": hard,
        },
    )
    return LlmConfigResponse(config=_row_to_list_item(row))


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
