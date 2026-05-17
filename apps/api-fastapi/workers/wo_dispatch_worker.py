"""Beta-2 phase 0.2 — auto-dispatch worker.

Q1=B locked: this worker is the **sole canonical authority** for moving
a `pending` Work Order into `processing`. ``POST /work_orders`` returns
201 with status=pending immediately; submit latency stays short and
idempotence is solved once here, not split between request/response and
background recovery.

Per acceptance criterion #11 the worker reuses the existing dispatch
helpers (``runtime.tier_1_aiden`` / ``runtime.tier_1_5_pm`` /
``runtime.tier_2_subagents`` / ``adapter.dispatch.dispatch_gamma_for_package``)
rather than re-implementing Tier 1 / 1.5 / 2 logic. ADR-020 dual-gate
behavior is inherited transparently.

Ticks every ``IWO3_WO_DISPATCH_TICK_SECONDS`` (default 15s). Reads the
`pending` queue across all tenants on a bypass connection, then opens a
fresh tenant-scoped transaction for each WO so RLS policies + audit
rows land in the right tenant. Idempotent via the
``execution_cycles.trigger='auto_dispatch'`` rowmark — a WO with a
recent successful auto-dispatch attempt is skipped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import asyncpg

from authz.audit_writer import write_audit_row


log = logging.getLogger("iwo3.wo_dispatch_worker")
logging.basicConfig(level=logging.INFO)


DEFAULT_TICK_SECONDS = 15
DEFAULT_BATCH_LIMIT = 25

ENV_TICK = "IWO3_WO_DISPATCH_TICK_SECONDS"
ENV_BATCH = "IWO3_WO_DISPATCH_BATCH_LIMIT"
ENV_DISABLED = "IWO3_WO_DISPATCH_WORKER_DISABLED"


def _tick_seconds() -> int:
    raw = os.environ.get(ENV_TICK)
    if not raw:
        return DEFAULT_TICK_SECONDS
    try:
        return max(5, int(raw))  # floor at 5s to avoid hot-looping
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


# Per-tenant agent_system actor cache — same pattern as poll_worker.
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


async def _list_pending_wos(
    conn: asyncpg.Connection, batch: int
) -> list[asyncpg.Record]:
    """Bypass-path read across all tenants. Returns one row per WO that
    needs an auto-dispatch attempt — `pending` status AND no
    `execution_cycles` row already records an `auto_dispatch` attempt
    for it. Idempotent on restart: the cycle-row write happens BEFORE
    the LLM call so a crashed worker won't re-fire."""
    return await conn.fetch(
        """
        SELECT wo.id::text         AS work_order_id,
               wo.client_id::text  AS client_id,
               wo.title            AS title,
               wo.description      AS description
          FROM work_orders wo
         WHERE wo.status = 'pending'
           AND NOT EXISTS (
             SELECT 1 FROM execution_cycles ec
              WHERE ec.work_order_id = wo.id
                AND ec.trigger = 'auto_dispatch'
           )
         ORDER BY wo.created_at ASC
         LIMIT $1
        """,
        batch,
    )


async def _record_auto_dispatch_cycle(
    conn: asyncpg.Connection,
    *,
    work_order_id: str,
    client_id: str,
    actor_user_id: str,
) -> str:
    """Write the execution_cycles row BEFORE invoking Aiden. On a worker
    restart mid-dispatch, the row's presence prevents a re-fire (R-047
    mitigation per scope proposal). Returns the cycle id."""
    return await conn.fetchval(
        """
        INSERT INTO execution_cycles
          (work_order_id, client_id, cycle_number, trigger,
           initiated_by_user_id, started_at, reason)
        VALUES ($1::uuid, $2::uuid,
                COALESCE((SELECT MAX(cycle_number) FROM execution_cycles
                            WHERE work_order_id = $1::uuid), 0) + 1,
                'auto_dispatch'::execution_cycle_trigger,
                $3::uuid, now(),
                'wo_dispatch_worker tick')
        RETURNING id::text
        """,
        work_order_id,
        client_id,
        actor_user_id,
    )


async def dispatch_one_wo(
    pool: asyncpg.Pool, work_order_id: str, client_id: str
) -> str:
    """Open a tenant-scoped transaction and drive the WO through Aiden
    Tier 1 + (work_order_brief → Tier 2 + auto-handoff) or
    (workflow_brief → Tier 1.5 PM instantiation). Returns a counts-key
    string for observability."""
    # Local imports avoid runtime → adapter circular-import hazard at
    # module-load time + keep the worker file's import surface narrow.
    from adapter.dispatch import (
        DispatchError,
        dispatch_gamma_for_package,
    )
    from runtime.budgets import LlmBudgetExceeded
    from runtime.tier_1_aiden import (
        AidenInvocationError,
        AidenNoConfig,
        invoke_aiden_tier_1,
    )
    from runtime.tier_1_5_pm import (
        PmError,
        instantiate_workflow_from_brief,
    )
    from runtime.tier_2_subagents import (
        Tier2Error,
        invoke_tier_2,
        produce_output_package,
    )
    from wo_wf.transitions import (
        IllegalTransition,
        transition_work_order,
    )

    async with pool.acquire() as conn:
        actor = await _resolve_agent_user_for_tenant(conn, client_id)
        if actor is None:
            log.warning(
                "wo_dispatch_worker: no agent_system user for tenant %s",
                client_id,
            )
            return "no_agent_user"

        async with conn.transaction():
            await _enter_tenant_scope(conn, client_id)

            # Idempotence + restart-safety: write the cycle BEFORE the LLM
            # call. If the worker dies mid-call, the row pre-records the
            # attempt and the next tick filters this WO out.
            cycle_id = await _record_auto_dispatch_cycle(
                conn,
                work_order_id=work_order_id,
                client_id=client_id,
                actor_user_id=actor,
            )

            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor,
                event="work_order.auto_dispatch_attempted",
                target_type="work_order",
                target_id=work_order_id,
                metadata={"cycle_id": cycle_id},
            )

            wo = await conn.fetchrow(
                """
                SELECT id::text   AS id,
                       title,
                       description
                  FROM work_orders
                 WHERE id = $1::uuid AND client_id = $2::uuid
                """,
                work_order_id,
                client_id,
            )
            if wo is None:
                # Race with another worker / tenant deletion; not an error.
                return "wo_disappeared"

            intake_text = (
                f"{wo['title']}\n\n{wo['description'] or ''}".strip()
            )

            try:
                decision = await invoke_aiden_tier_1(
                    conn,
                    intake_text=intake_text,
                    client_id=client_id,
                    actor_user_id=actor,
                    work_order_id=wo["id"],
                )
            except (AidenNoConfig, AidenInvocationError, LlmBudgetExceeded) as exc:
                await write_audit_row(
                    conn,
                    client_id=client_id,
                    actor_user_id=actor,
                    event="work_order.auto_dispatch_failed",
                    target_type="work_order",
                    target_id=wo["id"],
                    metadata={
                        "stage": "aiden_tier_1",
                        "kind": getattr(exc, "kind", type(exc).__name__),
                        "detail": str(exc),
                    },
                )
                return "aiden_failed"

            if decision.decision_kind == "clarification":
                # Aiden asked a question — leave the WO as `pending` for
                # operator follow-up. Don't audit as failed; the cycle
                # row already records the attempt.
                await write_audit_row(
                    conn,
                    client_id=client_id,
                    actor_user_id=actor,
                    event="work_order.auto_dispatch_succeeded",
                    target_type="work_order",
                    target_id=wo["id"],
                    metadata={
                        "decision_kind": "clarification",
                        "question": (
                            decision.clarification.question
                            if decision.clarification
                            else None
                        ),
                    },
                )
                return "clarification"

            if decision.decision_kind == "assistant_reply":
                # Operator submitted a WO with conversational intake.
                # Aiden replied in voice; leave the WO as pending so the
                # operator can rewrite with actual deliverable language.
                await write_audit_row(
                    conn,
                    client_id=client_id,
                    actor_user_id=actor,
                    event="work_order.auto_dispatch_succeeded",
                    target_type="work_order",
                    target_id=wo["id"],
                    metadata={
                        "decision_kind": "assistant_reply",
                        "headline": (
                            decision.assistant_reply.headline
                            if decision.assistant_reply
                            else None
                        ),
                    },
                )
                return "assistant_reply"

            # Tool-call → execute → re-invoke loop. Mirrors the chat-
            # route pattern at routes/aiden.py:408-464 with WO semantics:
            #   1. Execute the requested tool on the live tenant-scoped
            #      connection. `execute_tool` writes its own audit row
            #      via the standard sub_agent.tool_called / .failed
            #      vocabulary (Loop Eta), so we do not double-audit.
            #   2. Re-invoke Aiden Tier-1 once with the tool result
            #      injected as context. The followup decision REPLACES
            #      the current one; existing handlers (clarification,
            #      assistant_reply, work_order_brief, workflow_brief,
            #      and the trailing unknown-handler) catch it
            #      naturally.
            #   3. Cap at 1 round-trip. If the followup also returns
            #      tool_call, the existing decision_kind_unknown handler
            #      catches it — the cap is enforced implicitly without
            #      a second branch here.
            #   4. Tool failures and followup-invoke failures audit
            #      work_order.auto_dispatch_failed with explicit stage
            #      labels; return strings keep run_one_tick's per-tick
            #      bucket counts truthful.
            if decision.decision_kind == "tool_call" and decision.tool_call:
                from runtime.aiden_tools import (  # local to avoid cycle
                    ToolExecutionError,
                    ToolNotFoundError,
                    execute_tool,
                )

                tool_call = decision.tool_call
                try:
                    tool_result = await execute_tool(
                        conn,
                        tool_name=tool_call.tool_name,
                        args=tool_call.args,
                        client_id=client_id,
                        actor_user_id=actor,
                    )
                except (ToolNotFoundError, ToolExecutionError) as exc:
                    await write_audit_row(
                        conn,
                        client_id=client_id,
                        actor_user_id=actor,
                        event="work_order.auto_dispatch_failed",
                        target_type="work_order",
                        target_id=wo["id"],
                        metadata={
                            "stage": "tool_call",
                            "tool_name": tool_call.tool_name,
                            "kind": type(exc).__name__,
                            "detail": str(exc),
                        },
                    )
                    return "tool_failed"

                followup_intake = (
                    f"{intake_text}\n\n"
                    f"[TOOL RESULT — {tool_call.tool_name}]\n"
                    f"{json.dumps(tool_result, default=str, indent=2)}\n"
                    f"[END TOOL RESULT]\n\n"
                    f"Compose your final decision using the data above. "
                    f"Do not call another tool."
                )
                try:
                    decision = await invoke_aiden_tier_1(
                        conn,
                        intake_text=followup_intake,
                        client_id=client_id,
                        actor_user_id=actor,
                        work_order_id=wo["id"],
                    )
                except (
                    AidenNoConfig,
                    AidenInvocationError,
                    LlmBudgetExceeded,
                ) as exc:
                    await write_audit_row(
                        conn,
                        client_id=client_id,
                        actor_user_id=actor,
                        event="work_order.auto_dispatch_failed",
                        target_type="work_order",
                        target_id=wo["id"],
                        metadata={
                            "stage": "tool_call_followup",
                            "tool_name": tool_call.tool_name,
                            "kind": getattr(exc, "kind", type(exc).__name__),
                            "detail": str(exc),
                        },
                    )
                    return "followup_failed"

                # Followup may itself be clarification / assistant_reply.
                # Re-run the same short-circuit handlers so those paths
                # behave identically whether they were the first decision
                # or the followup decision.
                if decision.decision_kind == "clarification":
                    await write_audit_row(
                        conn,
                        client_id=client_id,
                        actor_user_id=actor,
                        event="work_order.auto_dispatch_succeeded",
                        target_type="work_order",
                        target_id=wo["id"],
                        metadata={
                            "decision_kind": "clarification",
                            "via_tool_call": tool_call.tool_name,
                            "question": (
                                decision.clarification.question
                                if decision.clarification
                                else None
                            ),
                        },
                    )
                    return "clarification"
                if decision.decision_kind == "assistant_reply":
                    await write_audit_row(
                        conn,
                        client_id=client_id,
                        actor_user_id=actor,
                        event="work_order.auto_dispatch_succeeded",
                        target_type="work_order",
                        target_id=wo["id"],
                        metadata={
                            "decision_kind": "assistant_reply",
                            "via_tool_call": tool_call.tool_name,
                            "headline": (
                                decision.assistant_reply.headline
                                if decision.assistant_reply
                                else None
                            ),
                        },
                    )
                    return "assistant_reply"
                # Otherwise fall through with the new decision; the
                # transition_work_order + work_order_brief / workflow_brief
                # handlers below handle it. A second tool_call hits the
                # trailing decision_kind_unknown handler (1-round-trip cap).

            # Move to processing. IllegalTransition is non-fatal — the
            # WO may have been transitioned by another path concurrently.
            try:
                await transition_work_order(
                    conn,
                    work_order_id=wo["id"],
                    client_id=client_id,
                    actor_user_id=actor,
                    to="processing",
                    reason=f"auto_dispatch:{decision.decision_kind}",
                )
            except IllegalTransition:
                pass

            if decision.decision_kind == "work_order_brief":
                brief = decision.work_order_brief
                assert brief is not None
                # Loop Lambda — assemble Tier-2 memory bundle for the
                # async dispatch path. Operator identity falls back to
                # WO submitter (or sentinel if NULL — see wrappers.py).
                from memory.wrappers import (  # local to avoid cycle
                    memory_context_builder_for_subagent,
                )
                tier2_bundle = await memory_context_builder_for_subagent(
                    conn,
                    client_id=client_id,
                    work_order_id=wo["id"],
                    sub_agent_role=brief.assigned_role,
                    intake_text=intake_text,
                    actor_user_id=actor,
                )
                try:
                    envelope = await invoke_tier_2(
                        conn,
                        role=brief.assigned_role,
                        intake_text=intake_text,
                        content_blocks=brief.content_blocks or {},
                        work_order_id=wo["id"],
                        client_id=client_id,
                        actor_user_id=actor,
                        memory_block=tier2_bundle.block,
                    )
                except (Tier2Error, LlmBudgetExceeded) as exc:
                    await write_audit_row(
                        conn,
                        client_id=client_id,
                        actor_user_id=actor,
                        event="work_order.auto_dispatch_failed",
                        target_type="work_order",
                        target_id=wo["id"],
                        metadata={
                            "stage": "tier_2",
                            "kind": getattr(exc, "kind", type(exc).__name__),
                            "detail": str(exc),
                        },
                    )
                    return "tier_2_failed"

                # Pull operator-supplied template_profile_id if present
                # (Beta-2 phase 0.1 propagation, mirrored from the route).
                requested_template_id: Optional[str] = None
                # lint:bypass-rls-explain="worker is in a tenant-scoped tx (set_config + SET LOCAL ROLE iwo3_app); work_orders RLS filters to the active tenant transparently"
                wo_ro_row = await conn.fetchrow(
                    "SELECT requested_outputs::text AS ro FROM work_orders WHERE id = $1::uuid",
                    wo["id"],
                )
                if wo_ro_row is not None and wo_ro_row["ro"]:
                    try:
                        ro = json.loads(wo_ro_row["ro"])
                        tpl = ro.get("template_profile_id")
                        if isinstance(tpl, str) and tpl:
                            requested_template_id = tpl
                    except (json.JSONDecodeError, AttributeError):
                        pass

                pkg_id = await produce_output_package(
                    conn,
                    envelope=envelope,
                    title=decision.title or wo["title"],
                    work_order_id=wo["id"],
                    workflow_execution_id=None,
                    template_profile_id=requested_template_id,
                    client_id=client_id,
                    actor_user_id=actor,
                    correlation_id=f"auto_dispatch:{wo['id']}",
                )

                # Auto-handoff to Gamma when applicable. Failure here
                # doesn't roll back the package — operator can /render.
                handoff_id: Optional[str] = None
                if envelope.output_kind.startswith("gamma_"):
                    try:
                        result = await dispatch_gamma_for_package(
                            conn,
                            output_package_id=pkg_id,
                            client_id=client_id,
                            actor_user_id=actor,
                        )
                        handoff_id = result.handoff_id
                    except DispatchError as exc:
                        await write_audit_row(
                            conn,
                            client_id=client_id,
                            actor_user_id=actor,
                            event="adapter_dispatch.failed",
                            target_type="output_package",
                            target_id=pkg_id,
                            metadata={
                                "kind": exc.kind,
                                "detail": exc.detail,
                                "stage": "auto_dispatch_post_package_worker",
                            },
                        )

                await write_audit_row(
                    conn,
                    client_id=client_id,
                    actor_user_id=actor,
                    event="work_order.auto_dispatch_succeeded",
                    target_type="work_order",
                    target_id=wo["id"],
                    metadata={
                        "decision_kind": "work_order_brief",
                        "output_package_id": pkg_id,
                        "handoff_id": handoff_id,
                    },
                )
                return "work_order_brief"

            if decision.decision_kind == "workflow_brief":
                brief = decision.workflow_brief
                assert brief is not None
                # Loop Lambda — assemble PM memory bundle for the
                # async workflow-instantiation path. Bundle is
                # MEMORY_BUDGET_TIER_1_5 (1.5K).
                from memory.wrappers import (  # local to avoid cycle
                    memory_context_builder_for_workflow,
                )
                pm_bundle = await memory_context_builder_for_workflow(
                    conn,
                    client_id=client_id,
                    work_order_id=wo["id"],
                    workflow_execution_id=None,
                    intake_text=intake_text,
                    actor_user_id=actor,
                )
                try:
                    inst = await instantiate_workflow_from_brief(
                        conn,
                        brief=brief,
                        intake_text=intake_text,
                        aiden_summary=decision.summary,
                        work_order_id=wo["id"],
                        client_id=client_id,
                        actor_user_id=actor,
                        memory_block=pm_bundle.block,
                    )
                except PmError as exc:
                    await write_audit_row(
                        conn,
                        client_id=client_id,
                        actor_user_id=actor,
                        event="work_order.auto_dispatch_failed",
                        target_type="work_order",
                        target_id=wo["id"],
                        metadata={
                            "stage": "tier_1_5_pm",
                            "detail": str(exc),
                        },
                    )
                    return "pm_failed"

                await write_audit_row(
                    conn,
                    client_id=client_id,
                    actor_user_id=actor,
                    event="work_order.auto_dispatch_succeeded",
                    target_type="work_order",
                    target_id=wo["id"],
                    metadata={
                        "decision_kind": "workflow_brief",
                        "workflow_execution_id": inst.workflow_execution_id,
                        "step_count": len(inst.step_run_ids),
                    },
                )
                return "workflow_brief"

            # Unknown decision kind — log + count, no exception.
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor,
                event="work_order.auto_dispatch_failed",
                target_type="work_order",
                target_id=wo["id"],
                metadata={
                    "stage": "decision_kind_unknown",
                    "decision_kind": decision.decision_kind,
                },
            )
            return "decision_kind_unknown"


async def run_one_tick(pool: asyncpg.Pool) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with pool.acquire() as conn:
        rows = await _list_pending_wos(conn, _batch_limit())
    if not rows:
        return counts
    log.info("wo_dispatch_worker: tick — %d candidate WOs", len(rows))
    for row in rows:
        try:
            kind = await dispatch_one_wo(
                pool, row["work_order_id"], row["client_id"]
            )
        except Exception as exc:  # noqa: BLE001 — worker boundary
            log.exception(
                "wo_dispatch_worker: WO %s tenant %s raised: %s",
                row["work_order_id"],
                row["client_id"],
                exc,
            )
            kind = "exception"
        counts[kind] = counts.get(kind, 0) + 1
    log.info("wo_dispatch_worker: tick complete — %s", counts)
    return counts


async def wo_dispatch_worker_loop(pool: asyncpg.Pool) -> None:
    if _disabled():
        log.info(
            "wo_dispatch_worker: disabled via %s; not starting", ENV_DISABLED
        )
        return
    interval = _tick_seconds()
    log.info("wo_dispatch_worker: starting (tick=%ds)", interval)
    try:
        while True:
            try:
                await run_one_tick(pool)
            except asyncpg.PostgresError as exc:
                log.exception("wo_dispatch_worker: tick db error: %s", exc)
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "wo_dispatch_worker: unexpected tick error: %s", exc
                )
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("wo_dispatch_worker: stopping (cancelled)")
        raise
