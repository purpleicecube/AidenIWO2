"""Workspace filing — where a produced output lands.

Restores the IWO2 shape. `server/workspace-filing.ts` there filed every
deliverable under a date folder and then a per-work-order folder:

    05_Artifacts/<date>/<order-slug>_<id8>/<filename>

IWO3 replaced that with a single hardcoded destination — find the
folder literally named `Outputs`, drop the file in, flat. Everything
any agent ever produced landed in one heap, so an operator asking
"where is my document?" had no better answer than a UUID. Restored
here as:

    Outputs/<YYYY-MM-DD>/<order-slug>_<id8>/<filename>

with an operator override: Aiden can be told "put this in a folder
called Press Office" and route the output there instead (see
`runtime/tools/workspace.py`).

Every helper is idempotent — filing twice for the same work order
reuses the same folders rather than creating `2026-09-05 (1)`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import asyncpg


# Folder names are operator-visible and become part of a path, so they
# are kept conservative: lowercase words joined by hyphens, no slashes
# (which would imply nesting), no leading dots (hidden-file semantics).
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_MAX_SLUG = 48

# A folder name the operator may legitimately choose. Rejects path
# separators and traversal outright rather than sanitising them into
# something the operator did not ask for.
_VALID_FOLDER_NAME = re.compile(r"^[^/\\\x00]{1,120}$")


def slugify(text: str, *, max_len: int = _MAX_SLUG) -> str:
    """`"KLEAR.ai Press Office Spec"` → `"klear-ai-press-office-spec"`."""
    slug = _SLUG_STRIP.sub("-", (text or "").lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def date_folder_name(now: Optional[datetime] = None) -> str:
    """UTC date, `YYYY-MM-DD`. UTC because work orders, audit rows and
    handoffs are all stamped in UTC; a local-time folder name would not
    line up with the audit trail an operator cross-references."""
    return (now or datetime.now(timezone.utc)).astimezone(
        timezone.utc
    ).strftime("%Y-%m-%d")


def order_folder_name(title: str, work_order_id: str) -> str:
    """`"<slug>_<first 8 of uuid>"`.

    The id suffix is not decoration: two work orders can carry the same
    title on the same day, and without it the second one's outputs would
    silently land among the first one's.
    """
    return f"{slugify(title)}_{(work_order_id or '')[:8] or 'nowo'}"


def is_valid_folder_name(name: str) -> bool:
    """Operator-supplied names only. Rejects separators and traversal —
    a folder called `../..` or `a/b` would either escape the tenant tree
    or silently mean something other than what was typed."""
    name = (name or "").strip()
    if not name or name in {".", ".."}:
        return False
    return bool(_VALID_FOLDER_NAME.match(name))


async def root_folder_id(
    conn: asyncpg.Connection, client_id: str
) -> Optional[str]:
    return await conn.fetchval(
        """
        SELECT id::text FROM workspace_folders
         WHERE client_id = $1::uuid AND parent_folder_id IS NULL
           AND name = '/' AND deleted_at IS NULL
         LIMIT 1
        """,
        client_id,
    )


async def ensure_child_folder(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    parent_folder_id: str,
    name: str,
    created_by_user_id: str,
) -> str:
    """Return the id of `parent/name`, creating it if absent.

    Idempotent under concurrency: two workers filing at the same instant
    both try the INSERT, one loses on the unique constraint, and the
    loser re-reads rather than failing the filing.
    """
    # `workspace_folders_sibling_name_uniq` is UNIQUE on
    # (client_id, parent_folder_id, name) and is NOT partial — a
    # SOFT-DELETED sibling still occupies the name. So the lookup must
    # consider deleted rows too, or we INSERT into a name that is
    # taken, catch the unique violation, re-read with
    # `deleted_at IS NULL`, find nothing and return None. Review finding
    # 2026-09-05 (P2): that None then propagated as a missing parent —
    # either a false success or an output filed at the wrong level.
    #
    # A soft-deleted folder of the right name is REVIVED rather than
    # worked around: the alternative is inventing `Outputs (1)`, which
    # is exactly the non-idempotent behaviour this function exists to
    # prevent, and the operator's own deleted folder reappearing where
    # they put it is the least surprising outcome.
    row = await conn.fetchrow(
        """
        SELECT id::text AS id, deleted_at
          FROM workspace_folders
         WHERE client_id = $1::uuid AND parent_folder_id = $2::uuid
           AND name = $3
         LIMIT 1
        """,
        client_id,
        parent_folder_id,
        name,
    )
    if row is not None:
        if row["deleted_at"] is not None:
            await conn.execute(
                "UPDATE workspace_folders SET deleted_at = NULL, "
                "updated_at = now() WHERE id = $1::uuid",
                row["id"],
            )
        return row["id"]
    try:
        return await conn.fetchval(
            """
            INSERT INTO workspace_folders
              (client_id, parent_folder_id, name, created_by_user_id)
            VALUES ($1::uuid, $2::uuid, $3, $4::uuid)
            RETURNING id::text
            """,
            client_id,
            parent_folder_id,
            name,
            created_by_user_id,
        )
    except asyncpg.UniqueViolationError:
        # Concurrent creator won the race. Re-read WITHOUT the
        # deleted_at predicate for the same reason as above; a None here
        # would be a silent filing failure.
        raced = await conn.fetchrow(
            """
            SELECT id::text AS id, deleted_at
              FROM workspace_folders
             WHERE client_id = $1::uuid AND parent_folder_id = $2::uuid
               AND name = $3
             LIMIT 1
            """,
            client_id,
            parent_folder_id,
            name,
        )
        if raced is None:
            raise
        if raced["deleted_at"] is not None:
            await conn.execute(
                "UPDATE workspace_folders SET deleted_at = NULL, "
                "updated_at = now() WHERE id = $1::uuid",
                raced["id"],
            )
        return raced["id"]


async def ensure_outputs_folder(
    conn: asyncpg.Connection, *, client_id: str, created_by_user_id: str
) -> Optional[str]:
    root = await root_folder_id(conn, client_id)
    if not root:
        return None
    return await ensure_child_folder(
        conn,
        client_id=client_id,
        parent_folder_id=root,
        name="Outputs",
        created_by_user_id=created_by_user_id,
    )


async def resolve_filing_folder(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    created_by_user_id: str,
    work_order_id: Optional[str],
    title: str,
    override_folder_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Where this output should land.

    `override_folder_id` wins when supplied and still live — that is the
    operator having said "put it in Press Office". Otherwise the default
    `Outputs/<date>/<slug>_<id8>` is created as needed.

    Returns None only when the tenant has no root folder at all, which
    the caller must treat as "file failed", never as "file at root".
    """
    if override_folder_id:
        ok = await conn.fetchval(
            """
            SELECT id::text FROM workspace_folders
             WHERE id = $1::uuid AND client_id = $2::uuid
               AND deleted_at IS NULL
            """,
            override_folder_id,
            client_id,
        )
        if ok:
            return ok
        # Fall through to the default rather than dropping the output:
        # a deleted override folder must not lose the deliverable.

    outputs = await ensure_outputs_folder(
        conn, client_id=client_id, created_by_user_id=created_by_user_id
    )
    if not outputs:
        return None
    dated = await ensure_child_folder(
        conn,
        client_id=client_id,
        parent_folder_id=outputs,
        name=date_folder_name(now),
        created_by_user_id=created_by_user_id,
    )
    # The folder name must be derived from the WORK ORDER, never from
    # the caller's `title`. A multi-step workflow calls this once per
    # step and each step passes its own title ("Mark (draft)",
    # "Hank (render)"), so slugging the caller's title scattered ONE
    # work order's deliverables across N sibling folders — the exact
    # opposite of the grouping this function exists to provide. Caught
    # by an end-to-end run on 2026-09-05: a single HTML work order
    # produced `create-html-landing-page-with-press-office-summa_b0d5…`
    # AND `create-html-landing-page-summarizing-press-offic_b0d5…`.
    #
    # `title` remains the fallback for outputs with no work order.
    folder_title = title
    if work_order_id:
        wo_title = await conn.fetchval(
            "SELECT title FROM work_orders WHERE id = $1::uuid",
            work_order_id,
        )
        if wo_title:
            folder_title = wo_title
    return await ensure_child_folder(
        conn,
        client_id=client_id,
        parent_folder_id=dated,
        name=order_folder_name(folder_title, work_order_id or ""),
        created_by_user_id=created_by_user_id,
    )


async def folder_path(
    conn: asyncpg.Connection, *, client_id: str, folder_id: str
) -> str:
    """Human-readable path, e.g. `Outputs/2026-09-05/press-office_d147a99e`.

    Aiden answers "where is my document?" with this, so it must be a
    real path read from the database — never composed from what the
    model believes the structure to be.
    """
    rows = await conn.fetch(
        """
        WITH RECURSIVE up AS (
          SELECT id, parent_folder_id, name, 0 AS depth
            FROM workspace_folders
           WHERE id = $1::uuid AND client_id = $2::uuid
          UNION ALL
          SELECT f.id, f.parent_folder_id, f.name, up.depth + 1
            FROM workspace_folders f
            JOIN up ON f.id = up.parent_folder_id
           WHERE f.client_id = $2::uuid
        )
        SELECT name, depth FROM up ORDER BY depth DESC
        """,
        folder_id,
        client_id,
    )
    names = [r["name"] for r in rows if r["name"] != "/"]
    return "/".join(names) if names else "/"
