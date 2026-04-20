"""Loop 7 Phase 7.1 — canonical Python audit writer.

Python mirror of `packages/contracts/audit/writer.ts` (`writeAuditRow`).
The Phase 4.4 `no-raw-audit-insert` lint rule allowlists this file as
the only Python path that may `INSERT INTO action_audit_log`. All
FastAPI handlers + Depends that need to write audit rows must call
`write_audit_row(...)`.

Policy parity with TS (ADR-014):
  - Every privileged mutation writes one audit row with a locked
    `AUDIT_EVENTS` key as `action`.
  - `authz.denied` (Loop 4 Phase 2) is written from the dep factory
    before raising HTTPException(403); TS `requirePermission` does
    the same.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg


async def write_audit_row(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    event: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """Insert a row into `action_audit_log` and return its id.

    Runs on whatever connection the caller supplies. If the connection
    is in tenant-scoped mode (SET LOCAL ROLE iwo3_app +
    app.current_client_id), RLS will refuse a client_id mismatch via
    WITH CHECK. If the connection is bypass-path (iwo3 superuser), the
    write succeeds unconditionally — used by `require_permission_dep`
    to log denials without fighting RLS on no-membership cases.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO action_audit_log
          (client_id, actor_user_id, action, target_type, target_id,
           metadata, created_at)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, now())
        RETURNING id
        """,
        client_id,
        actor_user_id,
        event,
        target_type,
        target_id,
        json.dumps(metadata or {}),
    )
    return str(row["id"])
