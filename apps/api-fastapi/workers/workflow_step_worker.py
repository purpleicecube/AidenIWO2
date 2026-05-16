"""BUG-067 — workflow step auto-advance worker.

Closes the gap shipped through CAP-A..CAP-G: those loops shipped the
branded-chain runtime (content_brief → render → brand_qa → deliver)
and the `POST /workflows/{execution_id}/run_next_step` endpoint to
advance individual steps, but no background worker actually picked up
pending step_runs. Result: every multi-step `workflow_brief` dispatch
created a `workflow_execution` with all step_runs in `pending` and
sat there indefinitely, since the Streamlit UI also had no advance
affordance.

This worker mirrors the `wo_dispatch_worker` pattern exactly:

  - Ticks every IWO3_WORKFLOW_STEP_TICK_SECONDS (default 10s; floor 5s)
  - Reads a bypass-path list of `(execution_id, client_id)` pairs that
    have status='running' AND at least one pending step_run
  - For each execution it opens a tenant-scoped transaction, resolves
    the agent_system actor for that tenant, builds a memory bundle,
    and invokes `execute_step_run` on the next pending step (one step
    per execution per tick — keeps fairness across in-flight WOs)
  - Crashed mid-step → the step_run stays in whatever status
    `execute_step_run` left it; next tick will re-discover and retry
    only if status is still `pending`. Idempotent on restart.
  - Disabled via IWO3_WORKFLOW_STEP_WORKER_DISABLED (mirrors the other
    workers' env shape so the test conftest can disable all three with
    one default).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import asyncpg

from authz.audit_writer import write_audit_row


log = logging.getLogger("iwo3.workflow_step_worker")


DEFAULT_TICK_SECONDS = 10
DEFAULT_BATCH_LIMIT = 25

ENV_TICK = "IWO3_WORKFLOW_STEP_TICK_SECONDS"
ENV_BATCH = "IWO3_WORKFLOW_STEP_BATCH_LIMIT"
ENV_DISABLED = "IWO3_WORKFLOW_STEP_WORKER_DISABLED"


def _tick_seconds() -> int:
    raw = os.environ.get(ENV_TICK)
    if not raw:
        return DEFAULT_TICK_SECONDS
    try:
        return max(5, int(raw))
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


# Per-tenant agent_system actor cache — same shape as wo_dispatch_worker.
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
    await conn.execute(
        "SELECT set_config('app.current_client_id', $1, true)", client_id
    )
    await conn.execute("SET LOCAL ROLE iwo3_app")


async def _list_executions_with_pending_steps(
    conn: asyncpg.Connection, batch: int
) -> list[asyncpg.Record]:
    """Bypass-path scan across all tenants. Returns one row per
    running workflow_execution that has at least one pending
    step_run. Ordering: oldest execution first so long-running chains
    don't get starved by newly-arrived ones."""
    return await conn.fetch(
        """
        SELECT we.id::text         AS execution_id,
               we.client_id::text  AS client_id,
               we.created_at
          FROM workflow_executions we
         WHERE we.status = 'running'::workflow_execution_status
           AND EXISTS (
             SELECT 1 FROM workflow_step_runs sr
              WHERE sr.execution_id = we.id
                AND sr.status = 'pending'::workflow_step_run_status
           )
         ORDER BY we.created_at ASC
         LIMIT $1
        """,
        batch,
    )


async def advance_one_execution(
    pool: asyncpg.Pool,
    execution_id: str,
    client_id: str,
) -> str:
    """Open a tenant-scoped transaction, resolve actor + memory bundle
    for the next pending step, and call `execute_step_run`. Returns a
    short tag for the per-tick counts dict.

    Imports the runtime helpers lazily so a missing optional dep
    (e.g. chromadb during a partial install) doesn't break worker
    startup."""
    from runtime.tier_2_subagents import Tier2Error, execute_step_run
    from memory.wrappers import memory_context_builder_for_subagent

    async with pool.acquire() as conn:
        async with conn.transaction():
            await _enter_tenant_scope(conn, client_id)
            actor = await _resolve_agent_user_for_tenant(conn, client_id)
            if actor is None:
                log.warning(
                    "workflow_step_worker: no agent_system user for tenant "
                    "%s — skipping execution %s", client_id, execution_id,
                )
                return "no_agent_user"

            next_pending = await conn.fetchrow(
                """
                SELECT id::text AS id, step_key, step_order
                  FROM workflow_step_runs
                 WHERE execution_id = $1::uuid
                   AND status = 'pending'::workflow_step_run_status
                 ORDER BY step_order ASC
                 LIMIT 1
                """,
                execution_id,
            )
            if next_pending is None:
                # Execution still running but no pending step — likely a
                # race with another tick that already advanced it.
                return "no_pending_step"

            step_meta = await conn.fetchrow(
                """
                SELECT wts.assigned_sub_agent_key,
                       coalesce(wts.display_name, wts.step_key) AS intake_label,
                       we.work_order_id::text AS work_order_id
                  FROM workflow_step_runs sr
                  JOIN workflow_executions we ON we.id = sr.execution_id
                  JOIN workflow_template_steps wts
                    ON wts.template_id = we.template_id
                   AND wts.step_key = sr.step_key
                 WHERE sr.id = $1::uuid AND we.client_id = $2::uuid
                """,
                next_pending["id"],
                client_id,
            )
            step_role = (step_meta["assigned_sub_agent_key"] if step_meta else None) or "mark"
            step_intake = (step_meta["intake_label"] if step_meta else None) or next_pending["step_key"]
            step_wo_id = step_meta["work_order_id"] if step_meta else None

            step_bundle = await memory_context_builder_for_subagent(
                conn,
                client_id=client_id,
                work_order_id=step_wo_id,
                sub_agent_role=step_role,
                intake_text=step_intake,
                actor_user_id=actor,
            )

            try:
                await execute_step_run(
                    conn,
                    step_run_id=next_pending["id"],
                    client_id=client_id,
                    actor_user_id=actor,
                    memory_block=step_bundle.block,
                )
            except Tier2Error as exc:
                # execute_step_run already marks the step + writes
                # tier_2 audit. The worker logs separately so an
                # operator scanning the worker audit can see which
                # tick a step failed in.
                await write_audit_row(
                    conn,
                    client_id=client_id,
                    actor_user_id=actor,
                    event="workflow_step.auto_advance_failed",
                    target_type="workflow_step_run",
                    target_id=next_pending["id"],
                    metadata={
                        "execution_id": execution_id,
                        "step_key": next_pending["step_key"],
                        "kind": exc.args[0] if exc.args else "tier_2_failed",
                        "detail": str(exc),
                    },
                )
                return "tier_2_failed"

            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor,
                event="workflow_step.auto_advanced",
                target_type="workflow_step_run",
                target_id=next_pending["id"],
                metadata={
                    "execution_id": execution_id,
                    "step_key": next_pending["step_key"],
                    "step_order": next_pending["step_order"],
                },
            )
            return "advanced"


async def run_one_tick(pool: asyncpg.Pool) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with pool.acquire() as conn:
        rows = await _list_executions_with_pending_steps(conn, _batch_limit())
    if not rows:
        return counts
    log.info(
        "workflow_step_worker: tick — %d execution(s) with pending steps",
        len(rows),
    )
    for row in rows:
        try:
            kind = await advance_one_execution(
                pool, row["execution_id"], row["client_id"]
            )
        except Exception as exc:  # noqa: BLE001 — worker boundary
            log.exception(
                "workflow_step_worker: execution %s tenant %s raised: %s",
                row["execution_id"], row["client_id"], exc,
            )
            kind = "exception"
        counts[kind] = counts.get(kind, 0) + 1
    log.info("workflow_step_worker: tick complete — %s", counts)
    return counts


async def workflow_step_worker_loop(pool: asyncpg.Pool) -> None:
    if _disabled():
        log.info(
            "workflow_step_worker: disabled via %s; not starting", ENV_DISABLED,
        )
        return
    interval = _tick_seconds()
    log.info("workflow_step_worker: starting (tick=%ds)", interval)
    try:
        while True:
            try:
                await run_one_tick(pool)
            except asyncpg.PostgresError as exc:
                log.exception("workflow_step_worker: tick db error: %s", exc)
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "workflow_step_worker: unexpected tick error: %s", exc,
                )
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("workflow_step_worker: stopping (cancelled)")
        raise
