"""Loop Kappa — Memory V1.5 canonical facts table-driven refresh.

Rebuilds `clients.canonical_facts_blob` from the `canonical_facts`
table (where `is_active = true`), bumps `canonical_facts_revision`,
and invalidates the in-process cache.

Severity priority order (D-K3): critical → high → medium → low.
Within a severity, sort by version DESC then created_at ASC for
deterministic blob construction. Each fact is rendered as:

    ### [SEVERITY] (v{version}) authored {created_at_iso}
    <body>

Triggered by:
  - POST /canonical_facts (create)
  - PATCH /canonical_facts/{id} (update + severity changes)
  - DELETE /canonical_facts/{id} (soft-delete via is_active=false)

Tenant safety: every query carries explicit `client_id = $1`. RLS +
FORCE on the new `canonical_facts` table acts as the hard wall;
predicates are the safety belt (ADR-014 §Q4 keep_both posture).

Hybrid switch (D-K2): callers should prefer
`refresh_canonical_facts_for_tenant_hybrid()` in canonical_facts.py
which checks for table rows first; this module only handles the
table-driven path.
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from . import cache


logger = logging.getLogger(__name__)


_SEVERITY_PRIORITY: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


async def count_active_canonical_facts(
    conn: asyncpg.Connection,
    *,
    client_id: str,
) -> int:
    """Return the number of active canonical_facts rows for the
    tenant. Used by the hybrid switch to decide whether to run the
    table-driven path or fall back to the folder-driven path.
    """
    row = await conn.fetchrow(
        """
        SELECT count(*)::int AS active_count
        FROM canonical_facts
        WHERE client_id = $1::uuid
          AND is_active = true
        """,
        client_id,
    )
    return int(row["active_count"]) if row else 0


async def refresh_canonical_facts_from_table(
    conn: asyncpg.Connection,
    *,
    client_id: str,
) -> Optional[int]:
    """Rebuild `canonical_facts_blob` from the `canonical_facts` table.

    Returns the new `canonical_facts_revision`, or None on error.
    Wraps in savepoint so any failure cannot poison the caller's
    outer transaction.
    """
    try:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id::text          AS id,
                       severity          AS severity,
                       version           AS version,
                       body              AS body,
                       created_at        AS created_at
                FROM canonical_facts
                WHERE client_id = $1::uuid
                  AND is_active = true
                """,
                client_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "refresh_canonical_facts_from_table: query failed for "
            "client_id=%s: %s",
            client_id,
            exc,
        )
        return None

    if not rows:
        # Empty table for this tenant — clear the blob so memory
        # builder falls back to no canonical facts. Revision still
        # bumps to invalidate any cached non-empty blob.
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
                "refresh_canonical_facts_from_table: clear-blob update "
                "failed for client_id=%s: %s",
                client_id,
                exc,
            )
            return None
        cache.invalidate_canonical_facts(client_id)
        return int(row["canonical_facts_revision"]) if row else None

    # Sort: severity priority asc, then version desc, then created_at asc.
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            _SEVERITY_PRIORITY.get(r["severity"], 99),
            -int(r["version"] or 0),
            r["created_at"],
        ),
    )

    parts: list[str] = []
    for r in sorted_rows:
        sev = (r["severity"] or "").upper()
        ver = int(r["version"] or 1)
        ts = r["created_at"].isoformat() if r["created_at"] else "?"
        parts.append(f"### [{sev}] (v{ver}) authored {ts}")
        parts.append((r["body"] or "").strip())
        parts.append("")
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
            "refresh_canonical_facts_from_table: update failed for "
            "client_id=%s: %s",
            client_id,
            exc,
        )
        return None

    cache.invalidate_canonical_facts(client_id)
    return int(row["canonical_facts_revision"]) if row else None
