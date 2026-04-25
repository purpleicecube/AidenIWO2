"""MegaLoop Alpha α.5 — channel layer core helpers."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from channel.core import (
    AuthCodeExpired,
    AuthCodeNotConsumable,
    AuthCodeNotFound,
    consume_auth_code_and_bind,
    find_active_identity,
    issue_auth_code,
    mark_inbound_failed,
    mark_inbound_processed,
    mark_outbound_attempt_failed,
    mark_outbound_sent,
    queue_outbound_message,
    record_inbound_message,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])


async def _cleanup_channel_state() -> None:
    conn = await _connect()
    try:
        await conn.execute("DELETE FROM channel_messages WHERE client_id = $1::uuid", KLEAR_CLIENT)
        await conn.execute("DELETE FROM channel_identities WHERE client_id = $1::uuid", KLEAR_CLIENT)
        await conn.execute("DELETE FROM channel_auth_codes WHERE client_id = $1::uuid", KLEAR_CLIENT)
    finally:
        await conn.close()


@iwo3_db
def test_issue_auth_code_emits_audit_and_returns_code() -> None:
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            issued = await issue_auth_code(
                conn,
                client_id=KLEAR_CLIENT,
                issued_by_user_id=KLEAR_OPERATOR,
                channel_kind="telegram",
                ttl_minutes=5,
            )
            assert len(issued.code) >= 8
            assert issued.expires_at > datetime.now(timezone.utc)
            audit_count = await conn.fetchval(
                """
                SELECT count(*)::int FROM action_audit_log
                 WHERE action = 'channel_auth_code.issued'
                   AND target_id = $1
                """,
                issued.id,
            )
            assert audit_count == 1
        finally:
            await conn.close()
            await _cleanup_channel_state()

    asyncio.run(run())


@iwo3_db
def test_consume_auth_code_creates_active_identity() -> None:
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            issued = await issue_auth_code(
                conn,
                client_id=KLEAR_CLIENT,
                issued_by_user_id=KLEAR_OPERATOR,
                channel_kind="telegram",
            )
            chat_id = "tg_chat_42"
            bound = await consume_auth_code_and_bind(
                conn, code=issued.code, channel_kind="telegram",
                external_id=chat_id,
            )
            assert bound.client_id == KLEAR_CLIENT
            assert bound.user_id == KLEAR_OPERATOR

            ident = await find_active_identity(
                conn, channel_kind="telegram", external_id=chat_id
            )
            assert ident is not None
            assert ident.user_id == KLEAR_OPERATOR
            assert ident.client_id == KLEAR_CLIENT

            # Audit trail
            bound_audit = await conn.fetchval(
                """
                SELECT count(*)::int FROM action_audit_log
                 WHERE action = 'channel_identity.bound'
                   AND target_id = $1
                """,
                bound.identity_id,
            )
            assert bound_audit == 1
        finally:
            await conn.close()
            await _cleanup_channel_state()

    asyncio.run(run())


@iwo3_db
def test_consume_auth_code_rejects_unknown_code() -> None:
    async def run() -> None:
        conn = await _connect()
        try:
            with pytest.raises(AuthCodeNotFound):
                await consume_auth_code_and_bind(
                    conn, code="DOES_NOT_EXIST_AT_ALL",
                    channel_kind="telegram", external_id="tg_chat_x",
                )
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_consume_auth_code_rejects_double_consumption() -> None:
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            issued = await issue_auth_code(
                conn,
                client_id=KLEAR_CLIENT,
                issued_by_user_id=KLEAR_OPERATOR,
                channel_kind="telegram",
            )
            await consume_auth_code_and_bind(
                conn, code=issued.code, channel_kind="telegram",
                external_id="tg_chat_first",
            )
            with pytest.raises(AuthCodeNotConsumable):
                await consume_auth_code_and_bind(
                    conn, code=issued.code, channel_kind="telegram",
                    external_id="tg_chat_second",
                )
        finally:
            await conn.close()
            await _cleanup_channel_state()

    asyncio.run(run())


@iwo3_db
def test_inbound_lifecycle_received_to_processed() -> None:
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            issued = await issue_auth_code(
                conn,
                client_id=KLEAR_CLIENT,
                issued_by_user_id=KLEAR_OPERATOR,
                channel_kind="telegram",
            )
            bound = await consume_auth_code_and_bind(
                conn, code=issued.code, channel_kind="telegram",
                external_id="tg_chat_99",
            )
            ext_msg = f"tg_msg_{uuid.uuid4().hex[:10]}"
            inbound = await record_inbound_message(
                conn,
                client_id=bound.client_id,
                channel_kind="telegram",
                channel_identity_id=bound.identity_id,
                external_message_id=ext_msg,
                external_chat_id="tg_chat_99",
                payload={"text": "create wo: render the deck"},
                intent="create_wo",
                actor_user_id=bound.user_id,
            )
            await mark_inbound_processed(
                conn,
                client_id=bound.client_id,
                message_id=inbound.id,
                actor_user_id=bound.user_id,
                related_work_order_id=None,
            )
            status = await conn.fetchval(
                "SELECT status::text FROM channel_messages WHERE id = $1::uuid",
                inbound.id,
            )
            assert status == "processed"
        finally:
            await conn.close()
            await _cleanup_channel_state()

    asyncio.run(run())


@iwo3_db
def test_outbound_lifecycle_pending_to_sent_with_idempotency() -> None:
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            idem_key = f"tg_outbound_{uuid.uuid4().hex[:10]}"
            id1 = await queue_outbound_message(
                conn,
                client_id=KLEAR_CLIENT,
                channel_kind="telegram",
                channel_identity_id=None,
                external_chat_id="tg_chat_77",
                payload={"text": "hello!"},
                idempotency_key=idem_key,
                actor_user_id=KLEAR_OPERATOR,
            )
            # Re-queueing with the same idempotency key returns the
            # same row.
            id2 = await queue_outbound_message(
                conn,
                client_id=KLEAR_CLIENT,
                channel_kind="telegram",
                channel_identity_id=None,
                external_chat_id="tg_chat_77",
                payload={"text": "hello again"},
                idempotency_key=idem_key,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert id1 == id2

            await mark_outbound_sent(
                conn,
                client_id=KLEAR_CLIENT,
                message_id=id1,
                actor_user_id=KLEAR_OPERATOR,
                external_message_id="tg_external_id_42",
            )
            row = await conn.fetchrow(
                "SELECT status::text AS status, external_message_id, sent_at FROM channel_messages WHERE id = $1::uuid",
                id1,
            )
            assert row["status"] == "sent"
            assert row["external_message_id"] == "tg_external_id_42"
            assert row["sent_at"] is not None
        finally:
            await conn.close()
            await _cleanup_channel_state()

    asyncio.run(run())


@iwo3_db
def test_outbound_attempt_failed_does_not_terminate_unless_permanent() -> None:
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            mid = await queue_outbound_message(
                conn,
                client_id=KLEAR_CLIENT,
                channel_kind="telegram",
                channel_identity_id=None,
                external_chat_id="tg_chat_22",
                payload={"text": "x"},
                idempotency_key=f"tg_ofail_{uuid.uuid4().hex[:8]}",
                actor_user_id=KLEAR_OPERATOR,
            )
            # Transient failure: stays pending
            await mark_outbound_attempt_failed(
                conn,
                client_id=KLEAR_CLIENT,
                message_id=mid,
                actor_user_id=KLEAR_OPERATOR,
                error_detail="transient 502",
                permanent=False,
            )
            status = await conn.fetchval(
                "SELECT status::text FROM channel_messages WHERE id = $1::uuid",
                mid,
            )
            assert status == "pending"
            # Permanent failure: terminal
            await mark_outbound_attempt_failed(
                conn,
                client_id=KLEAR_CLIENT,
                message_id=mid,
                actor_user_id=KLEAR_OPERATOR,
                error_detail="invalid bot token",
                permanent=True,
            )
            status2 = await conn.fetchval(
                "SELECT status::text FROM channel_messages WHERE id = $1::uuid",
                mid,
            )
            assert status2 == "failed"
        finally:
            await conn.close()
            await _cleanup_channel_state()

    asyncio.run(run())


@iwo3_db
def test_find_active_identity_returns_none_for_unbound() -> None:
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            ident = await find_active_identity(
                conn, channel_kind="telegram",
                external_id="tg_chat_unbound_ever",
            )
            assert ident is None
        finally:
            await conn.close()

    asyncio.run(run())


# ── Pre-Beta β.5 — channel correctness hardening ──────────────────────


@iwo3_db
def test_inbound_uniq_is_chat_scoped_so_message_42_does_not_alias() -> None:
    """Telegram numbers messages per chat; the inbound UNIQUE must be
    (channel_kind, external_chat_id, external_message_id) so chat A's
    message #42 cannot collide with chat B's #42. Pre-β.5 this UPSERTed
    onto the wrong row."""
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            issued = await issue_auth_code(
                conn,
                client_id=KLEAR_CLIENT,
                issued_by_user_id=KLEAR_OPERATOR,
                channel_kind="telegram",
            )
            bound_a = await consume_auth_code_and_bind(
                conn, code=issued.code, channel_kind="telegram",
                external_id="tg_chat_AAA",
            )
            issued2 = await issue_auth_code(
                conn,
                client_id=KLEAR_CLIENT,
                issued_by_user_id=KLEAR_OPERATOR,
                channel_kind="telegram",
            )
            bound_b = await consume_auth_code_and_bind(
                conn, code=issued2.code, channel_kind="telegram",
                external_id="tg_chat_BBB",
            )

            inbound_a = await record_inbound_message(
                conn,
                client_id=bound_a.client_id,
                channel_kind="telegram",
                channel_identity_id=bound_a.identity_id,
                external_message_id="42",
                external_chat_id="tg_chat_AAA",
                payload={"text": "hi from A"},
                intent="unknown",
                actor_user_id=bound_a.user_id,
            )
            inbound_b = await record_inbound_message(
                conn,
                client_id=bound_b.client_id,
                channel_kind="telegram",
                channel_identity_id=bound_b.identity_id,
                external_message_id="42",
                external_chat_id="tg_chat_BBB",
                payload={"text": "hi from B"},
                intent="unknown",
                actor_user_id=bound_b.user_id,
            )

            # Distinct rows — pre-β.5 these would have been the SAME id.
            assert inbound_a.id != inbound_b.id
            count = await conn.fetchval(
                """
                SELECT count(*)
                  FROM channel_messages
                 WHERE channel_kind = 'telegram'::channel_kind
                   AND external_message_id = '42'
                   AND external_chat_id IN ('tg_chat_AAA', 'tg_chat_BBB')
                """
            )
            assert count == 2
        finally:
            await conn.close()
            await _cleanup_channel_state()

    asyncio.run(run())


@iwo3_db
def test_inbound_replay_within_same_chat_is_idempotent() -> None:
    """Same (chat, message_id) replays UPSERT onto the same row +
    bump attempts; this is the desired idempotency for at-least-once
    delivery from the worker."""
    async def run() -> None:
        await _cleanup_channel_state()
        conn = await _connect()
        try:
            issued = await issue_auth_code(
                conn,
                client_id=KLEAR_CLIENT,
                issued_by_user_id=KLEAR_OPERATOR,
                channel_kind="telegram",
            )
            bound = await consume_auth_code_and_bind(
                conn, code=issued.code, channel_kind="telegram",
                external_id="tg_chat_REPLAY",
            )

            first = await record_inbound_message(
                conn,
                client_id=bound.client_id,
                channel_kind="telegram",
                channel_identity_id=bound.identity_id,
                external_message_id="999",
                external_chat_id="tg_chat_REPLAY",
                payload={"text": "first"},
                intent="unknown",
                actor_user_id=bound.user_id,
            )
            again = await record_inbound_message(
                conn,
                client_id=bound.client_id,
                channel_kind="telegram",
                channel_identity_id=bound.identity_id,
                external_message_id="999",
                external_chat_id="tg_chat_REPLAY",
                payload={"text": "second"},
                intent="unknown",
                actor_user_id=bound.user_id,
            )
            assert first.id == again.id
            attempts = await conn.fetchval(
                "SELECT attempts FROM channel_messages WHERE id = $1::uuid",
                first.id,
            )
            # First insert leaves attempts at the default (0); the
            # UPSERT bumps it to 1. The point is that the replay does
            # not create a second row.
            assert attempts >= 1
        finally:
            await conn.close()
            await _cleanup_channel_state()

    asyncio.run(run())
