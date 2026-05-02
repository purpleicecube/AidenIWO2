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
from typing import Annotated, Any, Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from authz.audit_writer import write_audit_row
from contracts.enums import (
    ToolCategory,
    ToolDefaultTier,
    ToolRuntimeStatus,
)
from deps import (
    current_user_context,
    get_db_connection,
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
    list_openai_compatible_models,
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


# ── /llm/models ───────────────────────────────────────────────────────
#
# Architect-lock §5 exception (approved 2026-04-26): IWO2 has
# `GET /api/llm-settings/models?provider=X` driving its ModelSelector
# component. The Aiden Settings page needs the same data to populate
# the Model dropdown. This route is the IWO3 equivalent — same response
# shape, multi-tenant credential resolution.
#
# Lookup: pick any enabled `llm_configs` row in this tenant for the
# requested provider, resolve its `credential_ref:env:NAME` to the
# runtime API key, and proxy to the provider's `/models` endpoint.
# When no config exists for that provider, or the env var is unset,
# return `keyConfigured=false` with an empty list (not an error) — the
# caller will fall back to manual text entry, matching IWO2.


class ProviderModel(BaseModel):
    id: str
    name: str
    contextWindow: Optional[int] = None
    owned_by: Optional[str] = None


class ListModelsResponse(BaseModel):
    provider: str
    keyConfigured: bool
    models: list[ProviderModel]
    error: Optional[str] = None


@router.get(
    "/models",
    response_model=ListModelsResponse,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def list_provider_models(
    provider: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> ListModelsResponse:
    if provider not in known_providers():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_provider", "provider": provider},
        )
    if provider not in callable_providers():
        return ListModelsResponse(
            provider=provider,
            keyConfigured=False,
            models=[],
            error="provider_not_callable_in_phase_9_3",
        )

    row = await conn.fetchrow(
        """
        SELECT credential_ref, base_url
          FROM llm_configs
         WHERE client_id = $1
           AND provider = $2
           AND enabled = true
         ORDER BY agent_role
         LIMIT 1
        """,
        ctx["client_id"],
        provider,
    )
    if row is None:
        return ListModelsResponse(
            provider=provider, keyConfigured=False, models=[]
        )

    try:
        api_key = resolve_credential(row["credential_ref"])
    except LlmCredentialError:
        return ListModelsResponse(
            provider=provider, keyConfigured=False, models=[]
        )

    try:
        raw_models = list_openai_compatible_models(
            provider=provider,
            api_key=api_key,
            base_url=row["base_url"],
        )
    except LlmProviderError as exc:
        return ListModelsResponse(
            provider=provider,
            keyConfigured=True,
            models=[],
            error=f"{exc.kind}: {exc}",
        )

    return ListModelsResponse(
        provider=provider,
        keyConfigured=True,
        models=[ProviderModel(**m) for m in raw_models],
    )


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
    # Loop Eta phase 0 — surface the metadata jsonb so the Sub-Agents UI
    # can render the prompt_provenance badge ∈ {extracted_from_iwo2_live,
    # extracted_from_iwo2_static, authored_parity_approximation,
    # authored_net_new}. Field is optional; older rows without metadata
    # show "unknown" in the UI.
    metadata: Optional[dict[str, Any]] = None


class ListConfigsResponse(BaseModel):
    configs: list[ConfigListItem]


def _row_to_list_item(row: asyncpg.Record) -> ConfigListItem:
    state, env_name = _credential_state_for_ref(row["credential_ref"])
    raw_meta = row["metadata"] if "metadata" in row.keys() else None
    if isinstance(raw_meta, str):
        # asyncpg returns jsonb as text by default; parse to a dict.
        try:
            raw_meta = json.loads(raw_meta)
        except (TypeError, ValueError):
            raw_meta = None
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
        metadata=raw_meta,
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
               metadata,
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
    """Beta-2 phase 0.3.2 tri-state mutation contract.

    `prompt_action` is REQUIRED whenever `system_prompt` is in the body.
    Allowed values:
      - "set": replace the live prompt with `system_prompt` (must be non-empty)
      - "clear": drop the prompt back to NULL (system_prompt must be absent or null)
      - "unchanged": leave existing prompt untouched (system_prompt must be absent)
    Omitting `prompt_action` AND `system_prompt` together = no prompt change.
    Sending `system_prompt` without `prompt_action` is rejected as ambiguous
    (closes the "blind overwrite when non-empty" CODEX finding).

    `change_reason` is recorded on the version row for audit forensics.
    """

    display_name: Optional[str] = Field(None, min_length=1, max_length=160)
    description: Optional[str] = Field(None, max_length=4000)
    provider: Optional[str] = Field(None, min_length=1, max_length=32)
    model: Optional[str] = Field(None, min_length=1, max_length=128)
    base_url: Optional[str] = Field(None, max_length=256)
    credential_ref: Optional[str] = Field(None, min_length=1, max_length=256)
    options: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    prompt_action: Optional[Literal["unchanged", "set", "clear"]] = None
    system_prompt: Optional[str] = None
    change_reason: Optional[str] = Field(None, max_length=2000)


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

    # Phase 0.3 — every mutation snapshots into llm_config_versions.
    from llm.config_versioning import (
        fetch_current_config_row,
        snapshot_config_version,
    )

    new_row = await fetch_current_config_row(
        conn, config_id=row["id"], client_id=ctx["client_id"]
    )
    assert new_row is not None
    version = await snapshot_config_version(
        conn,
        config_row=new_row,
        change_action="create",
        change_reason="llm_config.create",
        changed_fields=None,
        actor_user_id=ctx["user_id"],
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
            "versionNumber": version["version_number"],
        },
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_config.versioned",
        target_type="llm_config_version",
        target_id=version["id"],
        metadata={
            "llmConfigId": row["id"],
            "agentRole": body.agent_role,
            "versionNumber": version["version_number"],
            "changeAction": "create",
        },
    )
    return LlmConfigResponse(config=_row_to_list_item(row))


def _resolve_prompt_action(
    body: UpdateLlmConfigRequest,
) -> tuple[bool, Optional[str]]:
    """Validate the tri-state prompt_action contract and return
    (apply_change, new_prompt_value). `apply_change=False` = leave the
    column untouched. `apply_change=True` + value=None = clear to NULL.
    Raises HTTPException(422) on ambiguous combos."""
    has_system_prompt = body.system_prompt is not None
    action = body.prompt_action

    if action is None:
        if has_system_prompt:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "ambiguous_prompt_payload",
                    "detail": (
                        "system_prompt was provided without prompt_action. "
                        "Phase 0.3.2 requires explicit tri-state intent: "
                        'prompt_action must be one of "set" | "clear" | "unchanged".'
                    ),
                },
            )
        return (False, None)

    if action == "unchanged":
        if has_system_prompt:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "prompt_action_conflict",
                    "detail": 'prompt_action="unchanged" must not be paired with system_prompt.',
                },
            )
        return (False, None)

    if action == "set":
        if not has_system_prompt or not (body.system_prompt or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "prompt_action_conflict",
                    "detail": 'prompt_action="set" requires a non-empty system_prompt value.',
                },
            )
        return (True, body.system_prompt)

    # action == "clear"
    if has_system_prompt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "prompt_action_conflict",
                "detail": 'prompt_action="clear" must not be paired with a system_prompt value.',
            },
        )
    return (True, None)


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
    """Beta-2 phase 0.3.2 — tri-state PATCH with versioning.

    Transaction shape:
      1. Validate inputs (tri-state, provider, credential_ref).
      2. Read OLD state.
      3. Apply UPDATE.
      4. Snapshot NEW state into llm_config_versions (change_action='update').
      5. Emit llm_config.versioned + llm_config.updated/disabled audit.
    """
    from llm.config_versioning import (
        compute_changed_fields,
        fetch_current_config_row,
        snapshot_config_version,
    )

    if body.credential_ref is not None:
        _validate_credential_ref(body.credential_ref)
    if body.provider is not None:
        _validate_provider(body.provider)

    apply_prompt_change, new_prompt_value = _resolve_prompt_action(body)

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
    if apply_prompt_change:
        _add("system_prompt", "${idx}", new_prompt_value)
    if body.options is not None:
        _add("options", "${idx}::jsonb", json.dumps(body.options))
    if body.enabled is not None:
        _add("enabled", "${idx}", body.enabled)

    if not sets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_fields_to_update"},
        )

    # Read OLD state for diff before mutation.
    old = await fetch_current_config_row(
        conn, config_id=config_id, client_id=ctx["client_id"]
    )
    if old is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "config_not_found", "id": config_id},
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
        # Should not happen — old read succeeded — but treat defensively.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "config_not_found", "id": config_id},
        )

    # Snapshot the NEW state.
    new_row = await fetch_current_config_row(
        conn, config_id=config_id, client_id=ctx["client_id"]
    )
    assert new_row is not None  # we just updated it
    changed_fields = compute_changed_fields(dict(old), dict(new_row))
    version = await snapshot_config_version(
        conn,
        config_row=new_row,
        change_action="update",
        change_reason=body.change_reason,
        changed_fields=changed_fields,
        actor_user_id=ctx["user_id"],
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
            "fieldsChanged": changed_fields,
            "promptAction": body.prompt_action,
            "versionNumber": version["version_number"],
        },
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_config.versioned",
        target_type="llm_config_version",
        target_id=version["id"],
        metadata={
            "llmConfigId": row["id"],
            "agentRole": row["agent_role"],
            "versionNumber": version["version_number"],
            "changeAction": "update",
            "changedFields": changed_fields,
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


# ── Beta-1.5 phase 2 / Q6 — persona library (read-only) ──────────────


class PersonaRow(BaseModel):
    id: str
    profile_key: str
    display_name: str
    scope: str
    status: str
    created_at: str
    updated_at: str


class PersonasResponse(BaseModel):
    personas: list[PersonaRow]


@router.get(
    "/personas",
    response_model=PersonasResponse,
    dependencies=[Depends(require_permission_dep("client:read"))],
)
async def list_personas(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> PersonasResponse:
    """Beta-1.5 phase 2 / Q6 — read-only persona library.

    Architect Q6 lock: reuse `prompt_profiles` rather than minting a
    new table. Status `active` rows are surfaced; archived rows stay
    hidden from the UI but remain in the table for audit forensics.
    Versioning + override application stay on the existing Loop 2
    surfaces.
    """
    rows = await conn.fetch(
        """
        SELECT id::text          AS id,
               profile_key,
               display_name,
               scope::text       AS scope,
               status::text      AS status,
               created_at::text  AS created_at,
               updated_at::text  AS updated_at
          FROM prompt_profiles
         WHERE status = 'active'
         ORDER BY scope, profile_key
        """
    )
    return PersonasResponse(
        personas=[PersonaRow(**dict(r)) for r in rows]
    )


# ── Beta-2 phase 0.3 — load + version + rollback surface ──────────────


class LlmConfigPromptResponse(BaseModel):
    id: str
    agent_role: str
    system_prompt: Optional[str] = None
    has_system_prompt: bool


@router.get(
    "/configs/{config_id}/prompt",
    response_model=LlmConfigPromptResponse,
    dependencies=[Depends(require_permission_dep("llm_config:write"))],
)
async def get_config_prompt(
    config_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> LlmConfigPromptResponse:
    """Phase 0.3.1 — writer-gated read of the actual system_prompt body
    so editors can pre-fill instead of blind-overwriting. Audited as
    `llm_config.prompt_read`."""
    try:
        row = await conn.fetchrow(
            """
            SELECT id::text         AS id,
                   agent_role,
                   system_prompt
              FROM llm_configs
             WHERE id = $1::uuid AND client_id = $2::uuid
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

    sp = row["system_prompt"]
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_config.prompt_read",
        target_type="llm_config",
        target_id=row["id"],
        metadata={
            "agentRole": row["agent_role"],
            "promptChars": len(sp) if sp else 0,
        },
    )
    return LlmConfigPromptResponse(
        id=row["id"],
        agent_role=row["agent_role"],
        system_prompt=sp,
        has_system_prompt=bool(sp and len(sp) > 0),
    )


class ConfigVersionListItem(BaseModel):
    id: str
    version_number: int
    agent_role: str
    provider: str
    model: str
    enabled: bool
    has_system_prompt: bool
    change_action: str
    change_reason: Optional[str] = None
    changed_fields: Optional[list[str]] = None
    created_at: str
    created_by_user_id: Optional[str] = None


class ListConfigVersionsResponse(BaseModel):
    versions: list[ConfigVersionListItem]


@router.get(
    "/configs/{config_id}/versions",
    response_model=ListConfigVersionsResponse,
    dependencies=[Depends(require_permission_dep("llm_config:write"))],
)
async def list_config_versions(
    config_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    limit: int = 50,
) -> ListConfigVersionsResponse:
    """Phase 0.3.3 — list version snapshots for one config, newest first."""
    limit = max(1, min(int(limit), 200))
    try:
        rows = await conn.fetch(
            """
            SELECT v.id::text                          AS id,
                   v.version_number                   AS version_number,
                   v.agent_role,
                   v.provider,
                   v.model,
                   v.enabled,
                   (v.system_prompt IS NOT NULL
                     AND length(v.system_prompt) > 0) AS has_system_prompt,
                   v.change_action,
                   v.change_reason,
                   v.changed_fields,
                   v.created_at::text                 AS created_at,
                   v.created_by_user_id::text         AS created_by_user_id
              FROM llm_config_versions v
             WHERE v.llm_config_id = $1::uuid
               AND v.client_id     = $2::uuid
             ORDER BY v.version_number DESC
             LIMIT $3
            """,
            config_id,
            ctx["client_id"],
            limit,
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_config_id", "value": config_id},
        )
    return ListConfigVersionsResponse(
        versions=[ConfigVersionListItem(**dict(r)) for r in rows]
    )


class RollbackRequest(BaseModel):
    version_id: str = Field(..., min_length=1, max_length=64)
    change_reason: Optional[str] = Field(None, max_length=2000)


@router.post(
    "/configs/{config_id}/rollback",
    response_model=LlmConfigResponse,
    dependencies=[Depends(require_permission_dep("llm_config:write"))],
)
async def rollback_config(
    config_id: str,
    body: RollbackRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> LlmConfigResponse:
    """Phase 0.3.3 — pick a prior version and apply it as a NEW mutation.

    The historical version row is NOT mutated. Rollback writes a fresh
    version row (change_action='rollback', rolled_back_from_version_id
    set), then UPDATEs llm_configs to match the chosen snapshot's fields.
    """
    from llm.config_versioning import (
        compute_changed_fields,
        fetch_current_config_row,
        fetch_version_by_id,
        snapshot_config_version,
    )

    target = await fetch_version_by_id(
        conn, version_id=body.version_id, client_id=ctx["client_id"]
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "version_not_found", "version_id": body.version_id},
        )
    if target["llm_config_id"] != config_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "version_belongs_to_different_config",
                "version_id": body.version_id,
                "expected_config_id": config_id,
                "actual_config_id": target["llm_config_id"],
            },
        )

    old = await fetch_current_config_row(
        conn, config_id=config_id, client_id=ctx["client_id"]
    )
    if old is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "config_not_found", "id": config_id},
        )

    # Apply target's fields to the live row.
    options_json = target["options"]  # already JSON text from fetch_version_by_id
    row = await conn.fetchrow(
        """
        UPDATE llm_configs
           SET provider       = $1,
               model          = $2,
               base_url       = $3,
               credential_ref = $4,
               system_prompt  = $5,
               options        = $6::jsonb,
               enabled        = $7,
               notes          = $8,
               display_name   = $9,
               description    = $10,
               updated_at     = now()
         WHERE id = $11::uuid AND client_id = $12::uuid
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
        target["provider"],
        target["model"],
        target["base_url"],
        target["credential_ref"],
        target["system_prompt"],
        options_json,
        target["enabled"],
        target["notes"],
        target["display_name"],
        target["description"],
        config_id,
        ctx["client_id"],
    )
    assert row is not None  # old read succeeded

    new_row = await fetch_current_config_row(
        conn, config_id=config_id, client_id=ctx["client_id"]
    )
    assert new_row is not None
    changed_fields = compute_changed_fields(dict(old), dict(new_row))
    version = await snapshot_config_version(
        conn,
        config_row=new_row,
        change_action="rollback",
        change_reason=body.change_reason,
        changed_fields=changed_fields,
        actor_user_id=ctx["user_id"],
        rolled_back_from_version_id=target["id"],
    )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_config.rolled_back",
        target_type="llm_config",
        target_id=row["id"],
        metadata={
            "agentRole": row["agent_role"],
            "fromVersionId": target["id"],
            "fromVersionNumber": target["version_number"],
            "newVersionNumber": version["version_number"],
            "changedFields": changed_fields,
        },
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="llm_config.versioned",
        target_type="llm_config_version",
        target_id=version["id"],
        metadata={
            "llmConfigId": row["id"],
            "agentRole": row["agent_role"],
            "versionNumber": version["version_number"],
            "changeAction": "rollback",
            "rolledBackFromVersionId": target["id"],
            "changedFields": changed_fields,
        },
    )
    return LlmConfigResponse(config=_row_to_list_item(row))


# ── Loop Eta phase 1 — tool catalog + sub-agent tool assignments ──────
#
# Three endpoints per IWO3_LOOP_ETA_SCOPE_PROPOSAL §4:
#
#   GET  /tool_catalog                       — global, tenant-agnostic
#   GET  /llm/configs/{id}/tools             — catalog joined with assignment
#   PUT  /llm/configs/{id}/tools/{tool_key}  — toggle enabled (soft revoke)
#
# Schema + RBAC + audit events are locked in spine commit c756cda
# (migration 0022) — see db/schema/tool_catalog.ts +
# db/schema/sub_agent_tools.ts + packages/contracts/audit/events.ts.


# Catalog routes live on a separate router so the prefix is `/tool_catalog`
# rather than `/llm/tool_catalog`. The router is wired in main.py via
# `tool_catalog_router` exposed at module level.

tool_catalog_router = APIRouter(prefix="/tool_catalog", tags=["tool_catalog"])


class ToolCatalogRow(BaseModel):
    tool_key: str
    display_name: str
    description: str
    category: ToolCategory
    runtime_status: ToolRuntimeStatus
    args_schema: dict[str, Any]
    default_tier: ToolDefaultTier
    iwo2_origin: Optional[str] = None
    enabled: bool


class ListToolCatalogResponse(BaseModel):
    tools: list[ToolCatalogRow]


@tool_catalog_router.get(
    "",
    response_model=ListToolCatalogResponse,
    dependencies=[Depends(require_permission_dep("tool_catalog:read"))],
)
async def list_tool_catalog(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
    category: Optional[ToolCategory] = None,
    runtime_status: Optional[ToolRuntimeStatus] = None,
    default_tier: Optional[ToolDefaultTier] = None,
    enabled: bool = True,
) -> ListToolCatalogResponse:
    """List rows from the global tool_catalog.

    Tenant-agnostic — the catalog has no client_id, no RLS scoping, and
    `tool_catalog:read` is granted to every membership role. Use the
    bypass connection (`get_db_connection`) instead of the tenant-scoped
    one because we do not need RLS for a global registry read, and the
    bypass path matches the migration's documented intent.

    `enabled=true` by default — set `enabled=false` to inspect retired
    rows (or any boolean to drop the filter altogether is NOT supported
    in v1; toggle the param explicitly).
    """
    sql = [
        """
        SELECT tool_key,
               display_name,
               description,
               category::text       AS category,
               runtime_status::text AS runtime_status,
               args_schema,
               default_tier::text   AS default_tier,
               iwo2_origin,
               enabled
          FROM tool_catalog
         WHERE 1=1
        """
    ]
    args: list[Any] = []
    if category is not None:
        args.append(category)
        sql.append(f"AND category = ${len(args)}::tool_category")
    if runtime_status is not None:
        args.append(runtime_status)
        sql.append(
            f"AND runtime_status = ${len(args)}::tool_runtime_status"
        )
    if default_tier is not None:
        args.append(default_tier)
        sql.append(f"AND default_tier = ${len(args)}::tool_default_tier")
    args.append(enabled)
    sql.append(f"AND enabled = ${len(args)}")
    sql.append("ORDER BY category, default_tier, tool_key")
    rows = await conn.fetch("\n".join(sql), *args)
    return ListToolCatalogResponse(
        tools=[
            ToolCatalogRow(
                tool_key=r["tool_key"],
                display_name=r["display_name"],
                description=r["description"],
                category=r["category"],
                runtime_status=r["runtime_status"],
                args_schema=(
                    json.loads(r["args_schema"])
                    if isinstance(r["args_schema"], str)
                    else (r["args_schema"] or {})
                ),
                default_tier=r["default_tier"],
                iwo2_origin=r["iwo2_origin"],
                enabled=r["enabled"],
            )
            for r in rows
        ]
    )


# ── /llm/configs/{id}/tools — assignment surface ───────────────────────


class SubAgentToolAssignment(BaseModel):
    tool_key: str
    display_name: str
    category: ToolCategory
    runtime_status: ToolRuntimeStatus
    default_tier: ToolDefaultTier
    iwo2_origin: Optional[str] = None
    assigned: bool
    enabled: bool
    granted_at: Optional[str] = None
    granted_by_user_id: Optional[str] = None
    notes: Optional[str] = None


class SubAgentToolsResponse(BaseModel):
    llm_config_id: str
    agent_role: str
    tools: list[SubAgentToolAssignment]


# `Annotated[..., Depends(require_permission_dep(...))]` does not stack
# cleanly when both deps need to RUN (only the last takes effect for the
# Annotated dep). The two RBAC checks are wired via the FastAPI
# `dependencies=[...]` list on the route decorator, where every
# Depends in the list executes in order.

# NOTE: spec §4 calls for `llm_config:read` AND `sub_agent_tool:read`,
# but `llm_config:read` is not a seeded permission key — the vocabulary
# only mints `llm_config:write` and `llm_config:delete`, and the
# existing `GET /llm/configs` route gates on `client:read`. We mirror
# that here: `client:read` (tenant-scoped read capability) +
# `sub_agent_tool:read` (assignment-specific). Documented deviation.
_SUB_AGENT_TOOLS_READ_DEPS = [
    Depends(require_permission_dep("client:read")),
    Depends(require_permission_dep("sub_agent_tool:read")),
]


@router.get(
    "/configs/{config_id}/tools",
    response_model=SubAgentToolsResponse,
    dependencies=_SUB_AGENT_TOOLS_READ_DEPS,
)
async def get_sub_agent_tools(
    config_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> SubAgentToolsResponse:
    """Return the full tool_catalog joined with this config's
    assignment state. Unassigned tools surface with assigned=false,
    enabled=false so the UI can render a complete grid in one round
    trip.

    Tenant-scoped via `get_tenant_scoped_connection`; RLS hides
    cross-tenant llm_configs, so the existence check below returns
    None for cross-tenant ids and the route 404s.
    """
    try:
        cfg = await conn.fetchrow(
            """
            SELECT id::text AS id, agent_role
              FROM llm_configs
             WHERE id = $1::uuid
            """,
            config_id,
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_config_id", "value": config_id},
        )
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "llm_config_not_found", "id": config_id},
        )

    rows = await conn.fetch(
        """
        SELECT tc.tool_key,
               tc.display_name,
               tc.category::text       AS category,
               tc.runtime_status::text AS runtime_status,
               tc.default_tier::text   AS default_tier,
               tc.iwo2_origin,
               (sat.id IS NOT NULL)    AS assigned,
               COALESCE(sat.enabled, false)            AS enabled,
               sat.granted_at::text    AS granted_at,
               sat.granted_by_user_id::text AS granted_by_user_id,
               sat.notes
          FROM tool_catalog tc
          LEFT JOIN sub_agent_tools sat
            ON sat.tool_key = tc.tool_key
           AND sat.llm_config_id = $1::uuid
         WHERE tc.enabled = true
         ORDER BY tc.category, tc.default_tier, tc.tool_key
        """,
        config_id,
    )
    return SubAgentToolsResponse(
        llm_config_id=cfg["id"],
        agent_role=cfg["agent_role"],
        tools=[SubAgentToolAssignment(**dict(r)) for r in rows],
    )


# ── PUT /llm/configs/{id}/tools/{tool_key} — toggle assignment ─────────


class SetSubAgentToolRequest(BaseModel):
    enabled: bool
    notes: Optional[str] = Field(None, max_length=2000)


class SubAgentToolRow(BaseModel):
    id: str
    llm_config_id: str
    tool_key: str
    enabled: bool
    granted_at: str
    granted_by_user_id: Optional[str] = None
    notes: Optional[str] = None


@router.put(
    "/configs/{config_id}/tools/{tool_key}",
    response_model=SubAgentToolRow,
    dependencies=[Depends(require_permission_dep("sub_agent_tool:assign"))],
)
async def set_sub_agent_tool(
    config_id: str,
    tool_key: str,
    body: SetSubAgentToolRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> SubAgentToolRow:
    """Upsert a sub_agent_tools row for (tenant, llm_config_id,
    tool_key). Toggling `enabled=false` is the soft-revoke path — the
    row stays for history. There is no DELETE endpoint.

    Audit:
      - `sub_agent.tool_granted` when the new state is enabled=true
      - `sub_agent.tool_revoked` when the new state is enabled=false

    Both the upsert and the audit row write inside the tenant-scoped
    transaction opened by `get_tenant_scoped_connection`, so they
    commit or roll back as a single unit.
    """
    # 1. Validate llm_config exists in this tenant. RLS hides
    #    cross-tenant rows so a missing fetchrow == 404.
    try:
        cfg = await conn.fetchrow(
            """
            SELECT id::text AS id, agent_role
              FROM llm_configs
             WHERE id = $1::uuid
            """,
            config_id,
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_config_id", "value": config_id},
        )
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "llm_config_not_found", "id": config_id},
        )

    # 2. Validate tool_key exists in the global catalog.
    catalog_row = await conn.fetchrow(
        "SELECT tool_key, enabled FROM tool_catalog WHERE tool_key = $1",
        tool_key,
    )
    if catalog_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "tool_not_in_catalog", "tool_key": tool_key},
        )

    # 3. Read prior assignment state for audit metadata.
    prior = await conn.fetchrow(
        """
        SELECT enabled
          FROM sub_agent_tools
         WHERE llm_config_id = $1::uuid AND tool_key = $2
        """,
        config_id,
        tool_key,
    )
    prior_enabled = bool(prior["enabled"]) if prior is not None else False

    # 4. Upsert. ON CONFLICT (llm_config_id, tool_key) — the unique
    #    constraint defined on sub_agent_tools.
    upserted = await conn.fetchrow(
        """
        INSERT INTO sub_agent_tools
          (client_id, llm_config_id, tool_key, enabled,
           granted_at, granted_by_user_id, notes)
        VALUES ($1::uuid, $2::uuid, $3, $4, now(), $5::uuid, $6)
        ON CONFLICT (llm_config_id, tool_key) DO UPDATE SET
          enabled            = EXCLUDED.enabled,
          granted_at         = now(),
          granted_by_user_id = EXCLUDED.granted_by_user_id,
          notes              = EXCLUDED.notes
        RETURNING id::text                  AS id,
                  llm_config_id::text       AS llm_config_id,
                  tool_key,
                  enabled,
                  granted_at::text          AS granted_at,
                  granted_by_user_id::text  AS granted_by_user_id,
                  notes
        """,
        ctx["client_id"],
        config_id,
        tool_key,
        body.enabled,
        ctx["user_id"],
        body.notes,
    )
    assert upserted is not None  # RETURNING after a successful upsert

    # 5. Audit. Locked vocabulary keys per
    #    packages/contracts/audit/events.ts (LOOP_ETA_AUDIT_EVENTS).
    audit_event = (
        "sub_agent.tool_granted"
        if body.enabled
        else "sub_agent.tool_revoked"
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event=audit_event,
        target_type="sub_agent_tool",
        target_id=upserted["id"],
        metadata={
            "tool_name": tool_key,
            "llm_config_id": config_id,
            "agent_role": cfg["agent_role"],
            "prior_enabled": prior_enabled,
            "new_enabled": body.enabled,
        },
    )
    return SubAgentToolRow(**dict(upserted))
