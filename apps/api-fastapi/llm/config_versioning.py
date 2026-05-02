"""Beta-2 phase 0.3 — full-row snapshot helpers for `llm_configs`.

CODEX universal-slice locks (2026-05-01):
  - Every mutation to ``llm_configs`` writes a full-row snapshot row
    into ``llm_config_versions`` in the same transaction. No delta
    storage.
  - Rollback = pick a prior version, write a NEW version row carrying
    that snapshot's fields, then write the live row to match. Linear
    history; no pointer rollback.
  - Snapshots happen after the live row mutation — version N row is
    the state of the row immediately after mutation N. The 'initial'
    backfill (migration 0021) seeded version 1 from the existing
    seed state.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg


# Field set covered by snapshots. Mirrors `llm_configs` columns minus
# id / client_id / created_at / updated_at (those are identity / lifecycle).
SNAPSHOT_FIELDS: tuple[str, ...] = (
    "agent_role",
    "provider",
    "model",
    "base_url",
    "credential_ref",
    "system_prompt",
    "options",
    "enabled",
    "notes",
    "display_name",
    "description",
)


def compute_changed_fields(
    old: dict[str, Any], new: dict[str, Any]
) -> list[str]:
    """Return the names of fields whose values differ between two row
    dicts. Used to populate `llm_config_versions.changed_fields` for
    diff UI ergonomics."""
    changed: list[str] = []
    for f in SNAPSHOT_FIELDS:
        if old.get(f) != new.get(f):
            changed.append(f)
    return changed


async def fetch_current_config_row(
    conn: asyncpg.Connection, *, config_id: str, client_id: str
) -> Optional[asyncpg.Record]:
    """Read the live row, with options serialized as JSON text (asyncpg
    returns dict for jsonb but we want a stable text shape for diffs)."""
    return await conn.fetchrow(
        """
        SELECT id::text          AS id,
               client_id::text   AS client_id,
               agent_role,
               provider,
               model,
               base_url,
               credential_ref,
               system_prompt,
               options::text     AS options,
               enabled,
               notes,
               display_name,
               description
          FROM llm_configs
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        config_id,
        client_id,
    )


async def _next_version_number(
    conn: asyncpg.Connection, *, config_id: str
) -> int:
    n = await conn.fetchval(
        """
        SELECT COALESCE(MAX(version_number), 0) + 1
          FROM llm_config_versions
         WHERE llm_config_id = $1::uuid
        """,
        config_id,
    )
    return int(n) if n is not None else 1


async def snapshot_config_version(
    conn: asyncpg.Connection,
    *,
    config_row: asyncpg.Record,
    change_action: str,  # 'create' | 'update' | 'rollback'
    change_reason: Optional[str],
    changed_fields: Optional[list[str]],
    actor_user_id: Optional[str],
    rolled_back_from_version_id: Optional[str] = None,
) -> dict[str, Any]:
    """Insert one llm_config_versions row capturing the state of
    `config_row`. Caller must have done the UPDATE first; this records
    the after-state. Returns the inserted version's id + version_number.

    `change_action` must be one of: 'create' | 'update' | 'rollback'.
    The 'initial' marker is reserved for the migration backfill only."""
    if change_action not in {"create", "update", "rollback"}:
        raise ValueError(
            f"change_action must be create|update|rollback, got {change_action!r}"
        )

    version_number = await _next_version_number(
        conn, config_id=config_row["id"]
    )
    options_text = config_row["options"]
    options_json = options_text  # already JSON string from fetch_current_config_row

    row = await conn.fetchrow(
        """
        INSERT INTO llm_config_versions (
          llm_config_id, client_id, version_number,
          agent_role, provider, model, base_url, credential_ref,
          system_prompt, options, enabled, notes, display_name, description,
          change_action, change_reason, changed_fields,
          rolled_back_from_version_id, created_by_user_id
        ) VALUES (
          $1::uuid, $2::uuid, $3,
          $4, $5, $6, $7, $8,
          $9, $10::jsonb, $11, $12, $13, $14,
          $15, $16, $17::text[],
          $18::uuid, $19::uuid
        )
        RETURNING id::text AS id, version_number
        """,
        config_row["id"],
        config_row["client_id"],
        version_number,
        config_row["agent_role"],
        config_row["provider"],
        config_row["model"],
        config_row["base_url"],
        config_row["credential_ref"],
        config_row["system_prompt"],
        options_json,
        config_row["enabled"],
        config_row["notes"],
        config_row["display_name"],
        config_row["description"],
        change_action,
        change_reason,
        changed_fields,
        rolled_back_from_version_id,
        actor_user_id,
    )
    return {
        "id": row["id"],
        "version_number": int(row["version_number"]),
    }


async def fetch_version_by_id(
    conn: asyncpg.Connection, *, version_id: str, client_id: str
) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        """
        SELECT v.id::text                        AS id,
               v.llm_config_id::text             AS llm_config_id,
               v.version_number,
               v.agent_role, v.provider, v.model, v.base_url,
               v.credential_ref, v.system_prompt,
               v.options::text                   AS options,
               v.enabled, v.notes, v.display_name, v.description,
               v.change_action, v.change_reason, v.changed_fields,
               v.rolled_back_from_version_id::text AS rolled_back_from_version_id,
               v.created_at::text                AS created_at,
               v.created_by_user_id::text        AS created_by_user_id
          FROM llm_config_versions v
         WHERE v.id = $1::uuid AND v.client_id = $2::uuid
        """,
        version_id,
        client_id,
    )
