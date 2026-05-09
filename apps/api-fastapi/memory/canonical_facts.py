"""Loop Iota — Memory V1 canonical facts workspace hook.

Refreshes `clients.canonical_facts_blob` from the tenant's
`Canonical Facts/` workspace folder subtree, bumps
`canonical_facts_revision`, and invalidates the in-process cache.

Called by `routes/workspace.py` on every file or folder mutation. The
hook is best-effort — exceptions are logged and swallowed so a failure
in canonical-facts refresh never blocks the underlying workspace
operation.

Operator workflow:
  1. Operator creates a `Canonical Facts/` folder at tenant workspace
     root.
  2. Operator uploads `.md` files under it. Each file's extracted_text
     populates artifacts.extracted_text.
  3. Each upload triggers `refresh_canonical_facts_for_tenant()` which
     concatenates the extracted_text into `clients.canonical_facts_blob`
     with file-header separators, bumps revision, and invalidates the
     cache.
  4. The next chat turn from any operator on this tenant picks up the
     fresh blob via memory.context_builder.

The folder match is case-insensitive on the literal name "canonical
facts" — operators can use "Canonical Facts/" or "CANONICAL FACTS/" or
similar variants. Subfolders under any matched folder are also included
(operators can organize as `Canonical Facts/Pricing/...`,
`Canonical Facts/Compliance/...`).
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from . import cache
from .canonical_facts_service import (
    count_active_canonical_facts,
    refresh_canonical_facts_from_table,
)


logger = logging.getLogger(__name__)


_CANONICAL_FACTS_FOLDER_NAME = "canonical facts"


async def refresh_canonical_facts_for_tenant_hybrid(
    conn: asyncpg.Connection,
    *,
    client_id: str,
) -> Optional[int]:
    """Loop Kappa hybrid switch: prefer the `canonical_facts` table
    when populated; fall back to the workspace-folder path when the
    table is empty for this tenant.

    Returns the new `canonical_facts_revision`, or None on no-op.

    D-K2 rationale: tenants currently using the `Canonical Facts/`
    workspace folder must keep working without a forced migration.
    Adoption of the CRUD UI is voluntary and per-tenant; switchover
    is automatic on the first INSERT into `canonical_facts`.
    """
    try:
        active_count = await count_active_canonical_facts(
            conn, client_id=client_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "refresh_canonical_facts_for_tenant_hybrid: count failed "
            "for client_id=%s, falling back to folder path: %s",
            client_id,
            exc,
        )
        active_count = 0

    if active_count > 0:
        return await refresh_canonical_facts_from_table(
            conn, client_id=client_id
        )
    return await refresh_canonical_facts_for_tenant(
        conn, client_id=client_id
    )


async def refresh_canonical_facts_for_tenant(
    conn: asyncpg.Connection,
    *,
    client_id: str,
) -> Optional[int]:
    """Rebuild canonical_facts_blob for `client_id`. Returns the new
    revision number, or None on no-op (no Canonical Facts folder).

    SQL strategy:
      - Recursive CTE walks workspace_folders starting from any folder
        whose lower(name) = 'canonical facts' under the active tenant.
      - Self-FK descent collects every descendant.
      - Outer query joins artifacts on workspace_folder_id, orders by
        folder path + filename for deterministic blob construction,
        concatenates extracted_text with file-header separators.
      - Followed by UPDATE clients SET canonical_facts_blob = $blob,
        canonical_facts_revision = canonical_facts_revision + 1
        WHERE id = $client_id.

    Tenant safety: every CTE step + UPDATE carries explicit
    `client_id = $1`. RLS + FORCE on workspace_folders + artifacts
    serves as the hard wall (firewall Layer 3 belt + Layer 1 wall).
    """
    # Wrap the read query in a savepoint so any failure cannot poison
    # the caller's outer transaction (asyncpg connections are
    # transaction-scoped via FastAPI deps; an unhandled SQL error
    # aborts the whole transaction).
    try:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                WITH RECURSIVE canonical_roots AS (
                    SELECT id, name::text AS name,
                           parent_folder_id, 0 AS depth,
                           name::text AS path
                    FROM workspace_folders
                    WHERE client_id = $1::uuid
                      AND lower(name) = $2
                      AND deleted_at IS NULL
                ),
                tree AS (
                    SELECT id, name, parent_folder_id, depth, path
                    FROM canonical_roots
                    UNION ALL
                    SELECT wf.id,
                           wf.name::text,
                           wf.parent_folder_id,
                           t.depth + 1,
                           (t.path || '/' || wf.name)::text
                    FROM workspace_folders wf
                    JOIN tree t ON wf.parent_folder_id = t.id
                    WHERE wf.client_id = $1::uuid
                      AND wf.deleted_at IS NULL
                      AND t.depth < 6
                )
                SELECT a.id::text         AS id,
                       a.filename         AS filename,
                       t.path             AS folder_path,
                       coalesce(a.extracted_text, '') AS body
                FROM artifacts a
                JOIN tree t ON t.id = a.workspace_folder_id
                WHERE a.client_id = $1::uuid
                  AND a.extracted_text IS NOT NULL
                  AND length(trim(a.extracted_text)) > 0
                ORDER BY t.path, a.filename
                """,
                client_id,
                _CANONICAL_FACTS_FOLDER_NAME,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "refresh_canonical_facts_for_tenant: query failed for "
            "client_id=%s: %s",
            client_id,
            exc,
        )
        return None

    if not rows:
        # No canonical facts folder OR no extracted-text files inside.
        # Clear the blob to keep memory in sync; bump revision so any
        # cached non-empty blob is invalidated. Skip the UPDATE if the
        # blob is already NULL — avoids unnecessary revision bumps and
        # write contention. Wrapped in savepoint for the same reason
        # as the read above.
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE clients
                    SET canonical_facts_blob = NULL,
                        canonical_facts_revision = canonical_facts_revision + 1,
                        updated_at = now()
                    WHERE id = $1::uuid
                      AND canonical_facts_blob IS NOT NULL
                    RETURNING canonical_facts_revision
                    """,
                    client_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "refresh_canonical_facts_for_tenant: clear-blob update "
                "failed for client_id=%s: %s",
                client_id,
                exc,
            )
            return None
        cache.invalidate_canonical_facts(client_id)
        return int(row["canonical_facts_revision"]) if row else None

    # Concatenate with deterministic file-header separators.
    parts: list[str] = []
    for r in rows:
        parts.append(f"### {r['folder_path']}/{r['filename']}")
        parts.append((r["body"] or "").strip())
        parts.append("")  # blank line between files
    blob = "\n".join(parts).strip() + "\n"

    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE clients
                SET canonical_facts_blob = $2,
                    canonical_facts_revision = canonical_facts_revision + 1,
                    updated_at = now()
                WHERE id = $1::uuid
                RETURNING canonical_facts_revision
                """,
                client_id,
                blob,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "refresh_canonical_facts_for_tenant: update failed for "
            "client_id=%s: %s",
            client_id,
            exc,
        )
        return None

    cache.invalidate_canonical_facts(client_id)
    return int(row["canonical_facts_revision"]) if row else None
