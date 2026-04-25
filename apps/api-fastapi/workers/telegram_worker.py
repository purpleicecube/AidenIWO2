"""Pre-Beta β.4 — Telegram polling worker.

Drains every Telegram-bound tenant's `getUpdates` queue on a fixed
tick. For each parsed update:

  - bound chat: open a tenant-scoped tx → record_inbound_message →
    dispatch_intent → queue_outbound_message + deliver_outbound →
    mark_inbound_processed + update last_seen_at.
  - unbound chat with `/start CODE`: open a bypass connection →
    consume_auth_code_and_bind cross-tenant → reply confirmation
    via the bot's tenant-resolved token.
  - unbound chat with anything else: reply with a `/start` prompt
    (no DB write — bot needs no state for unbound chats).

Per-tenant configuration: token resolved from
`env_var_for_telegram_bot_token(client.designation)`; tenants
without the env var are skipped silently.

Disabled in CI via `IWO3_TELEGRAM_WORKER_DISABLED=true`. Mirrors
poll_worker's pattern for backpressure + cancellation.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import asyncpg

from channel.core import (
    AuthCodeExpired,
    AuthCodeNotConsumable,
    AuthCodeNotFound,
    consume_auth_code_and_bind,
    find_active_identity,
    mark_inbound_failed,
    mark_inbound_processed,
    mark_outbound_attempt_failed,
    mark_outbound_sent,
    queue_outbound_message,
    record_inbound_message,
)
from channel.intent_dispatcher import dispatch_intent
from channel.telegram import (
    TelegramAdapter,
    TelegramApiError,
    env_var_for_telegram_bot_token,
    parse_intent,
)


log = logging.getLogger("iwo3.telegram_worker")


DEFAULT_TICK_SECONDS = 10  # faster than gamma poll — chats expect quick replies
ENV_TICK = "IWO3_TELEGRAM_WORKER_TICK_SECONDS"
ENV_DISABLED = "IWO3_TELEGRAM_WORKER_DISABLED"


def _tick_seconds() -> int:
    raw = os.environ.get(ENV_TICK)
    if not raw:
        return DEFAULT_TICK_SECONDS
    try:
        return max(3, int(raw))  # floor at 3s; Telegram long-poll caps at 50s
    except ValueError:
        return DEFAULT_TICK_SECONDS


def _disabled() -> bool:
    return os.environ.get(ENV_DISABLED, "").lower() in {"true", "1", "yes"}


# Per-tenant cached state (offset, agent_system user_id). Reset on
# worker restart; the offset re-replay risk is documented in
# RISK_REGISTER R-022 and accepted for Alpha.
_tenant_offsets: dict[str, int] = {}
_agent_user_cache: dict[str, Optional[str]] = {}


async def _list_telegram_tenants(
    conn: asyncpg.Connection,
) -> list[asyncpg.Record]:
    """Return clients that resolve to a present TELEGRAM_BOT_TOKEN_*
    env var. Reads on bypass; the env-var presence is the gate."""
    rows = await conn.fetch(
        """
        SELECT id::text AS client_id, designation
          FROM clients
         WHERE status = 'active'::client_status
        """
    )
    out = []
    for r in rows:
        var_name = env_var_for_telegram_bot_token(r["designation"])
        if os.environ.get(var_name):
            out.append(r)
    return out


async def _resolve_agent_user(
    conn: asyncpg.Connection, client_id: str
) -> Optional[str]:
    if client_id in _agent_user_cache:
        return _agent_user_cache[client_id]
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
    _agent_user_cache[client_id] = user_id
    return user_id


async def _enter_tenant_scope(
    conn: asyncpg.Connection, client_id: str
) -> None:
    await conn.execute(
        "SELECT set_config('app.current_client_id', $1, true)", client_id
    )
    await conn.execute("SET LOCAL ROLE iwo3_app")


async def _send_unbound_prompt(
    adapter: TelegramAdapter, chat_id: str
) -> None:
    """Reply to an unbound chat with a /start hint. No DB writes."""
    try:
        await adapter.deliver_outbound(
            external_chat_id=chat_id,
            payload={
                "text": (
                    "This chat isn't bound to a tenant yet. Ask the "
                    "operator for a one-time code, then send "
                    "`/start <code>`."
                )
            },
        )
    except TelegramApiError as exc:
        log.warning(
            "telegram_worker: unbound prompt failed chat=%s: %s",
            chat_id,
            exc,
        )


async def _handle_start_binding(
    pool: asyncpg.Pool,
    adapter: TelegramAdapter,
    *,
    chat_id: str,
    code: str,
) -> None:
    """Cross-tenant /start CODE consumption. Bypass connection — the
    bot doesn't know the tenant until the consume succeeds."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                bound = await consume_auth_code_and_bind(
                    conn,
                    code=code,
                    channel_kind="telegram",
                    external_id=chat_id,
                )
            except AuthCodeNotFound:
                await adapter.deliver_outbound(
                    external_chat_id=chat_id,
                    payload={
                        "text": (
                            f"Code `{code}` not found. Ask the operator "
                            f"to issue a fresh one."
                        )
                    },
                )
                return
            except AuthCodeNotConsumable as exc:
                await adapter.deliver_outbound(
                    external_chat_id=chat_id,
                    payload={
                        "text": (
                            f"This code was already consumed or "
                            f"revoked (status={exc.args[0]})."
                        )
                    },
                )
                return
            except AuthCodeExpired:
                await adapter.deliver_outbound(
                    external_chat_id=chat_id,
                    payload={
                        "text": "This code expired. Ask for a new one."
                    },
                )
                return

    try:
        await adapter.deliver_outbound(
            external_chat_id=chat_id,
            payload={
                "text": (
                    f"✅ Bound. You can now use /status, create wo:, "
                    f"/approve, /reopen, /unblock."
                )
            },
        )
    except TelegramApiError as exc:
        log.warning(
            "telegram_worker: bind reply failed identity=%s: %s",
            bound.identity_id,
            exc,
        )


async def _handle_bound_inbound(
    pool: asyncpg.Pool,
    adapter: TelegramAdapter,
    *,
    update,
) -> None:
    """Bound-chat dispatch path. Writes inbound row, dispatches the
    intent, queues + delivers outbound."""
    async with pool.acquire() as conn:
        # Identity lookup is cross-tenant: the worker doesn't know
        # which tenant a chat_id belongs to until `find_active_identity`
        # answers. Read-only.
        identity = await find_active_identity(
            conn, channel_kind="telegram", external_id=update.chat_id
        )
        if identity is None:
            await _send_unbound_prompt(adapter, update.chat_id)
            return

        actor = await _resolve_agent_user(conn, identity.client_id)
        intent = parse_intent(update.text)

        # Inbound record + dispatch + outbox enqueue, all under one tx.
        async with conn.transaction():
            await _enter_tenant_scope(conn, identity.client_id)

            inbound = await record_inbound_message(
                conn,
                client_id=identity.client_id,
                channel_kind="telegram",
                channel_identity_id=identity.id,
                external_message_id=(
                    str(update.message_id)
                    if update.message_id is not None
                    else f"upd_{update.update_id}"
                ),
                external_chat_id=update.chat_id,
                payload={"text": update.text, "raw": update.raw},
                intent=intent.intent,
                actor_user_id=actor,
            )

            try:
                outcome = await dispatch_intent(
                    conn, intent=intent, identity=identity
                )
            except Exception as exc:  # noqa: BLE001 — channel boundary
                log.exception(
                    "telegram_worker: dispatch_intent raised: %s", exc
                )
                await mark_inbound_failed(
                    conn,
                    client_id=identity.client_id,
                    message_id=inbound.id,
                    actor_user_id=actor,
                    error_detail=f"dispatch_exception: {exc!r}",
                )
                return

            outbound_id = await queue_outbound_message(
                conn,
                client_id=identity.client_id,
                channel_kind="telegram",
                channel_identity_id=identity.id,
                external_chat_id=identity.external_id,
                payload={"text": outcome.reply_text},
                idempotency_key=(
                    f"tg:reply:{update.chat_id}:{update.update_id}"
                ),
                actor_user_id=actor,
                related_work_order_id=outcome.related_work_order_id,
                related_workflow_execution_id=outcome.related_workflow_execution_id,
            )

            await conn.execute(
                """
                UPDATE channel_identities
                   SET last_seen_at = now(), updated_at = now()
                 WHERE id = $1::uuid AND client_id = $2::uuid
                """,
                identity.id,
                identity.client_id,
            )

            await mark_inbound_processed(
                conn,
                client_id=identity.client_id,
                message_id=inbound.id,
                actor_user_id=actor,
                related_work_order_id=outcome.related_work_order_id,
                related_workflow_execution_id=outcome.related_workflow_execution_id,
            )

        # Outbox drain runs outside the inbound tx so a slow Telegram POST
        # can't hold a tenant-scoped lock; on failure the row stays pending
        # for the next tick.
        try:
            mid = await adapter.deliver_outbound(
                external_chat_id=identity.external_id,
                payload={"text": outcome.reply_text},
            )
        except TelegramApiError as exc:
            async with conn.transaction():
                await _enter_tenant_scope(conn, identity.client_id)
                await mark_outbound_attempt_failed(
                    conn,
                    client_id=identity.client_id,
                    message_id=outbound_id,
                    actor_user_id=actor,
                    error_detail=f"{exc.kind}: {exc.detail or ''}",
                )
            log.warning(
                "telegram_worker: outbound deliver failed: %s", exc
            )
            return

        async with conn.transaction():
            await _enter_tenant_scope(conn, identity.client_id)
            await mark_outbound_sent(
                conn,
                client_id=identity.client_id,
                message_id=outbound_id,
                actor_user_id=actor,
                external_message_id=mid,
            )


async def _process_update(
    pool: asyncpg.Pool, adapter: TelegramAdapter, update
) -> None:
    """Branch /start (cross-tenant binding) vs bound dispatch."""
    intent = parse_intent(update.text)
    if intent.intent == "start" and intent.arg:
        await _handle_start_binding(
            pool, adapter, chat_id=update.chat_id, code=intent.arg
        )
        return
    await _handle_bound_inbound(pool, adapter, update=update)


# Public alias for the webhook ingress. Beta-1.5 ε.5 architect-flagged
# fix: the webhook route MUST hand verified updates into the same
# persistence/dispatch pipeline as the long-poll worker — otherwise
# operators who disable the worker for production lose inbound
# processing entirely. The webhook constructs a TelegramAdapter from
# the resolved tenant's env_var and calls this entry point.
process_telegram_update = _process_update


async def _process_tenant(
    pool: asyncpg.Pool, client_id: str, designation: str
) -> int:
    var_name = env_var_for_telegram_bot_token(designation)
    adapter = TelegramAdapter(
        client_id=client_id,
        env_var=var_name,
        long_poll_seconds=1,  # short — the worker tick handles cadence
    )
    if client_id in _tenant_offsets:
        adapter.set_offset(_tenant_offsets[client_id])

    try:
        updates = await adapter.fetch_inbound_batch()
    except TelegramApiError as exc:
        log.warning(
            "telegram_worker: fetch failed tenant=%s: %s",
            client_id,
            exc,
        )
        return 0

    for u in updates:
        try:
            await _process_update(pool, adapter, u)
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "telegram_worker: update %s raised: %s",
                u.update_id,
                exc,
            )

    if adapter.next_offset is not None:
        _tenant_offsets[client_id] = adapter.next_offset
    return len(updates)


async def run_one_tick(pool: asyncpg.Pool) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with pool.acquire() as conn:
        tenants = await _list_telegram_tenants(conn)
    for t in tenants:
        try:
            n = await _process_tenant(pool, t["client_id"], t["designation"])
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "telegram_worker: tenant %s raised: %s", t["client_id"], exc
            )
            n = 0
        counts[t["client_id"]] = n
    return counts


async def telegram_worker_loop(pool: asyncpg.Pool) -> None:
    if _disabled():
        log.info(
            "telegram_worker: disabled via %s; not starting", ENV_DISABLED
        )
        return
    interval = _tick_seconds()
    log.info("telegram_worker: starting (tick=%ds)", interval)
    try:
        while True:
            try:
                await run_one_tick(pool)
            except Exception as exc:  # noqa: BLE001
                log.exception("telegram_worker: tick raised: %s", exc)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("telegram_worker: cancelled — shutting down")
        raise
