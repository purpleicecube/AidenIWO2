"""Audit-log partition maintenance.

`action_audit_log` is RANGE-partitioned by month. Migration
`0002_partition_action_audit_log.sql` creates three months of
partitions (2026-04 … 2026-06) and ships a self-healing helper,
`ensure_audit_partition_for(ts)`, with this comment:

    Callers (the audit writer in Loop 3+) SELECT this immediately
    before INSERT to self-heal a missing next-month partition in
    production.

Nothing ever called it. Neither `authz/audit_writer.py` nor its TS
twin `packages/contracts/audit/writer.ts` invoked the helper, and its
only caller in the repo was its own integration test. So on
2026-07-01 the last partition expired and every audited mutation
started failing with:

    CheckViolationError: no partition of relation
    "action_audit_log" found for row

That is ~55 call sites across 13 route modules — effectively every
privileged mutation in IWO3 — plus 60 vitest integration tests on any
freshly reset database.

WHY A WORKER AND NOT A CALL IN THE WRITER
The migration's original design (ensure-before-insert) costs a DDL
round-trip on every audited request and runs as whatever role the
request holds. `ensure_audit_partition_for` is NOT `SECURITY DEFINER`,
so under `SET LOCAL ROLE iwo3_app` it needs CREATE on schema public —
true on this dev box today, and exactly the grant a hardened
deployment revokes. It would then start failing at the worst moment.
This worker instead runs on the bypass pool (iwo3 superuser), once at
startup before traffic is served, then daily.

The window is deliberately generous: current month + `MONTHS_AHEAD`.
A process that boots once and runs for months still has partitions
long before it needs them, and the daily tick keeps the window rolling
for a long-lived process.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg


log = logging.getLogger("iwo3.audit_partition_worker")
logging.basicConfig(level=logging.INFO)


DEFAULT_TICK_SECONDS = 24 * 60 * 60  # daily
DEFAULT_MONTHS_AHEAD = 3

ENV_TICK = "IWO3_AUDIT_PARTITION_TICK_SECONDS"
ENV_MONTHS_AHEAD = "IWO3_AUDIT_PARTITION_MONTHS_AHEAD"
ENV_DISABLED = "IWO3_AUDIT_PARTITION_WORKER_DISABLED"


def _tick_seconds() -> int:
    raw = os.environ.get(ENV_TICK)
    if not raw:
        return DEFAULT_TICK_SECONDS
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_TICK_SECONDS


def _months_ahead() -> int:
    raw = os.environ.get(ENV_MONTHS_AHEAD)
    if not raw:
        return DEFAULT_MONTHS_AHEAD
    try:
        return max(1, min(int(raw), 24))
    except ValueError:
        return DEFAULT_MONTHS_AHEAD


def _disabled() -> bool:
    return os.environ.get(ENV_DISABLED, "").lower() in {"true", "1", "yes"}


def month_starts(now: datetime, months_ahead: int) -> list[datetime]:
    """First instant of the current month plus the next `months_ahead`.

    Pure — no clock read, no DB — so the December→January rollover is
    unit-testable without freezing time.
    """
    cursor = now.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    out = [cursor]
    for _ in range(months_ahead):
        # Step past the end of the current month, then snap back to the
        # 1st. Avoids 28/30/31 arithmetic and crosses the year boundary
        # without a special case.
        cursor = (cursor + timedelta(days=32)).replace(day=1)
        out.append(cursor)
    return out


async def ensure_audit_partitions(
    conn: asyncpg.Connection, *, now: datetime | None = None
) -> list[str]:
    """Ensure a partition exists for this month and the next N.

    Returns the month-start dates it ensured, as ISO date strings.
    Idempotent: `ensure_audit_partition_for` is a no-op when the
    partition is already attached.
    """
    helper_exists = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_proc "
        "WHERE proname = 'ensure_audit_partition_for')"
    )
    if not helper_exists:
        # A database predating migration 0002. Say so loudly rather
        # than pretending the window is healthy.
        log.error(
            "audit_partition: ensure_audit_partition_for() missing — "
            "database has not run migration 0002; audited writes will "
            "fail once the seeded partitions expire"
        )
        return []

    ensured: list[str] = []
    for start in month_starts(
        now or datetime.now(timezone.utc), _months_ahead()
    ):
        await conn.execute(
            "SELECT ensure_audit_partition_for($1::timestamptz)", start
        )
        ensured.append(start.date().isoformat())
    return ensured


async def run_one_tick(pool: asyncpg.Pool) -> list[str]:
    async with pool.acquire() as conn:
        return await ensure_audit_partitions(conn)


async def audit_partition_worker_loop(pool: asyncpg.Pool) -> None:
    """Long-running task. The FIRST pass is awaited by `main.lifespan`
    via `ensure_audit_partitions_at_startup`, so this loop only handles
    the ongoing roll."""
    if _disabled():
        log.info(
            "audit_partition_worker: disabled via %s; not starting",
            ENV_DISABLED,
        )
        return
    interval = _tick_seconds()
    log.info("audit_partition_worker: starting (tick=%ds)", interval)
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                ensured = await run_one_tick(pool)
                log.info("audit_partition: window ok %s", ensured)
            except asyncpg.PostgresError as exc:
                log.exception("audit_partition: db error: %s", exc)
            except Exception as exc:  # noqa: BLE001
                log.exception("audit_partition: unexpected error: %s", exc)
    except asyncio.CancelledError:
        log.info("audit_partition_worker: stopping (cancelled)")
        raise


async def ensure_audit_partitions_at_startup(pool: asyncpg.Pool) -> None:
    """Awaited in lifespan BEFORE the app serves traffic.

    A background first tick would race the first request, and a request
    that loses that race 500s on an audited write. Failure here is
    logged, never fatal — a broken partition window must not stop the
    API booting and serving reads.
    """
    try:
        ensured = await run_one_tick(pool)
        if ensured:
            log.info(
                "audit_partition: window ensured at startup %s", ensured
            )
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "audit_partition: STARTUP ENSURE FAILED (%s) — audited "
            "mutations may 500 until a partition exists",
            exc,
        )
