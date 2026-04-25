"""Loop 9 Phase 9.3 — effective LLM config resolution.

Resolution stack (highest priority first):
  1. The exact (client_id, agent_role) row in `llm_configs`.
  2. The (client_id, "aiden_tier_1") row — the tenant default.
  3. None — the caller decides (typically: emit `llm.failed` audit and
     return a typed "no_llm_configured" error).

Per CODEX guidance: prompt_profiles do not carry inline LLM bindings
in Phase 9.3. Future phases may layer a prompt-profile-level override
on top of this resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import asyncpg


TENANT_DEFAULT_ROLE = "aiden_tier_1"


@dataclass(frozen=True)
class EffectiveLlmConfig:
    config_id: str
    client_id: str
    requested_role: str
    resolved_role: str
    provider: str
    model: str
    base_url: Optional[str]
    credential_ref: str
    system_prompt: Optional[str]
    options: Mapping[str, Any]
    enabled: bool
    source: str  # "role" | "tenant_default"


async def resolve_llm_config(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    agent_role: str,
) -> Optional[EffectiveLlmConfig]:
    """Look up the effective LLM config for a (tenant, role) pair.

    Runs against whatever connection the caller supplies. If the
    connection is in tenant-scoped mode (`SET LOCAL ROLE iwo3_app +
    app.current_client_id`), RLS filters cross-tenant rows; the explicit
    `client_id = $1` predicate is the Phase 4.4 lint-rule belt.
    """
    direct = await conn.fetchrow(
        """
        SELECT id::text                AS id,
               client_id::text         AS client_id,
               agent_role,
               provider,
               model,
               base_url,
               credential_ref,
               system_prompt,
               options,
               enabled
          FROM llm_configs
         WHERE client_id = $1 AND agent_role = $2 AND enabled = true
        """,
        client_id,
        agent_role,
    )
    if direct:
        return _row_to_effective(direct, agent_role, "role")

    if agent_role == TENANT_DEFAULT_ROLE:
        return None

    fallback = await conn.fetchrow(
        """
        SELECT id::text                AS id,
               client_id::text         AS client_id,
               agent_role,
               provider,
               model,
               base_url,
               credential_ref,
               system_prompt,
               options,
               enabled
          FROM llm_configs
         WHERE client_id = $1 AND agent_role = $2 AND enabled = true
        """,
        client_id,
        TENANT_DEFAULT_ROLE,
    )
    if not fallback:
        return None
    return _row_to_effective(fallback, agent_role, "tenant_default")


def _row_to_effective(
    row: asyncpg.Record, requested_role: str, source: str
) -> EffectiveLlmConfig:
    raw_opts = row["options"]
    opts: Mapping[str, Any]
    if isinstance(raw_opts, dict):
        opts = raw_opts
    elif raw_opts is None:
        opts = {}
    else:
        # asyncpg can return jsonb as str when the codec isn't installed.
        import json

        opts = json.loads(raw_opts)
    return EffectiveLlmConfig(
        config_id=row["id"],
        client_id=row["client_id"],
        requested_role=requested_role,
        resolved_role=row["agent_role"],
        provider=row["provider"],
        model=row["model"],
        base_url=row["base_url"],
        credential_ref=row["credential_ref"],
        system_prompt=row["system_prompt"],
        options=opts,
        enabled=row["enabled"],
        source=source,
    )
