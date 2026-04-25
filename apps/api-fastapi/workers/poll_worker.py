"""MegaLoop Alpha α.1 — scheduled poll worker.

Walks every `output_handoffs` row in `submitted` state on every tick
and dispatches it through the adapter poll registry. Loops on the
FastAPI lifespan; stops cleanly on shutdown.

Runs as a background asyncio.Task started in `main.lifespan`. One
worker per FastAPI process; that's sufficient for Alpha (small
internal multi-user deployment per F1).

Tenant-scoped per handoff: the worker reads the `submitted` queue
on a bypass connection (iwo3 superuser, RLS bypassed) but opens a
fresh tenant-scoped transaction for each poll, so RLS policies fire
and audit rows land in the right tenant.

Honors the Loop 9 ADR-020 dual gate transparently — the registered
adapter handler enforces watchdog + cascade; the worker just calls
the registry on a tick.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import asyncpg

from adapter.poll_registry import poll_handoff_via_registry


log = logging.getLogger("iwo3.poll_worker")
logging.basicConfig(level=logging.INFO)


DEFAULT_TICK_SECONDS = 30
DEFAULT_BATCH_LIMIT = 50

ENV_TICK = "IWO3_POLL_WORKER_TICK_SECONDS"
ENV_BATCH = "IWO3_POLL_WORKER_BATCH_LIMIT"
ENV_DISABLED = "IWO3_POLL_WORKER_DISABLED"


def _tick_seconds() -> int:
    raw = os.environ.get(ENV_TICK)
    if not raw:
        return DEFAULT_TICK_SECONDS
    try:
        v = int(raw)
        return max(5, v)  # floor at 5s to avoid hot-looping
    except ValueError:
        return DEFAULT_TICK_SECONDS


def _batch_limit() -> int:
    raw = os.environ.get(ENV_BATCH)
    if not raw:
        return DEFAULT_BATCH_LIMIT
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_BATCH_LIMIT


def _disabled() -> bool:
    return os.environ.get(ENV_DISABLED, "").lower() in {"true", "1", "yes"}


# Each tenant carries a default agent_system user used as the actor
# for worker-triggered polls. Auto-discovered at tick time so seed
# additions land without code changes.
_AGENT_USER_CACHE: dict[str, Optional[str]] = {}


async def _resolve_agent_user_for_tenant(
    conn: asyncpg.Connection, client_id: str
) -> Optional[str]:
    if client_id in _AGENT_USER_CACHE:
        return _AGENT_USER_CACHE[client_id]
    user_id = await conn.fetchval(
        """
        SELECT u.id::text
          FROM users u
          JOIN client_memberships m
            ON m.user_id = u.id AND m.client_id = $1
         WHERE m.role = 'agent_system' AND m.status = 'active'
                                       AND u.status = 'active'
         ORDER BY u.created_at ASC
         LIMIT 1
        """,
        client_id,
    )
    _AGENT_USER_CACHE[client_id] = user_id
    return user_id


async def _enter_tenant_scope(
    conn: asyncpg.Connection, client_id: str
) -> None:
    """SET LOCAL app.current_client_id + SET LOCAL ROLE iwo3_app, matching
    the canonical tenant-scoped transaction pattern from ADR-015."""
    await conn.execute(
        "SELECT set_config('app.current_client_id', $1, true)",
        client_id,
    )
    await conn.execute("SET LOCAL ROLE iwo3_app")


async def _list_pending_handoffs(
    conn: asyncpg.Connection, batch: int
) -> list[asyncpg.Record]:
    """Bypass-path read across all tenants. Returns one row per
    handoff that needs a poll attempt."""
    return await conn.fetch(
        """
        SELECT h.id::text          AS handoff_id,
               h.client_id::text   AS client_id,
               cat.adapter_key
          FROM output_handoffs h
     LEFT JOIN adapter_catalog cat ON cat.id = h.adapter_catalog_id
         WHERE h.status = 'submitted'
         ORDER BY h.last_poll_at NULLS FIRST,
                  h.created_at ASC
         LIMIT $1
        """,
        batch,
    )


async def poll_one_handoff(
    pool: asyncpg.Pool, handoff_id: str, client_id: str
) -> str:
    """Open a tenant-scoped transaction, dispatch via the registry,
    return the outcome kind. Wraps everything in BEGIN..COMMIT so the
    audit row + handoff update + cascade transitions land atomically."""
    async with pool.acquire() as conn:
        # Resolve agent_system user on a fresh bypass connection
        # before entering tenant scope (so we don't accidentally hit
        # RLS while looking up the actor).
        actor = await _resolve_agent_user_for_tenant(conn, client_id)
        if actor is None:
            log.warning(
                "poll_worker: no agent_system user for tenant %s",
                client_id,
            )
            return "no_agent_user"

        async with conn.transaction():
            await _enter_tenant_scope(conn, client_id)
            outcome = await poll_handoff_via_registry(
                conn,
                handoff_id=handoff_id,
                client_id=client_id,
                actor_user_id=actor,
            )
            return outcome.kind


async def run_one_tick(pool: asyncpg.Pool) -> dict[str, int]:
    """Single worker tick — list candidates + poll each. Returns a
    counts-by-kind summary for observability."""
    counts: dict[str, int] = {}
    async with pool.acquire() as conn:
        rows = await _list_pending_handoffs(conn, _batch_limit())
    if not rows:
        return counts
    log.info("poll_worker: tick — %d candidate handoffs", len(rows))
    for row in rows:
        try:
            kind = await poll_one_handoff(
                pool, row["handoff_id"], row["client_id"]
            )
        except Exception as exc:  # noqa: BLE001 — worker boundary
            log.exception(
                "poll_worker: handoff %s tenant %s raised: %s",
                row["handoff_id"],
                row["client_id"],
                exc,
            )
            kind = "exception"
        counts[kind] = counts.get(kind, 0) + 1
    log.info("poll_worker: tick complete — %s", counts)
    return counts


async def poll_worker_loop(pool: asyncpg.Pool) -> None:
    """Long-running task — run ticks until cancelled."""
    if _disabled():
        log.info(
            "poll_worker: disabled via %s; not starting", ENV_DISABLED
        )
        return
    interval = _tick_seconds()
    log.info("poll_worker: starting (tick=%ds)", interval)
    try:
        while True:
            try:
                await run_one_tick(pool)
            except asyncpg.PostgresError as exc:
                log.exception("poll_worker: tick db error: %s", exc)
            except Exception as exc:  # noqa: BLE001
                log.exception("poll_worker: unexpected tick error: %s", exc)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("poll_worker: stopping (cancelled)")
        raise
