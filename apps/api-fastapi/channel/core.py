"""MegaLoop Alpha α.5 — channel layer core helpers.

Adapter-agnostic primitives that Telegram (α.6) + future Slack adapter
both build on. Stage A § B5 (channel_messages stores full payload), §
B6 (at-least-once + idempotency keys), § B7 (/start auth-code binding).

Public surface:
  - issue_auth_code()                generate one-time code + persist
  - consume_auth_code_and_bind()     code + external_id → channel_identity
  - find_active_identity()           (channel_kind, external_id) → identity row
  - record_inbound_message()         persist inbound + emit audit
  - mark_inbound_processed()         mark processed (or failed)
  - queue_outbound_message()         persist outbound row in pending status
  - mark_outbound_sent()             update sent_at + status
  - mark_outbound_failed()           record attempt failure
  - ChannelAdapter Protocol          surface the runtime expects per adapter

All helpers run inside the caller's transaction. Audit + DB writes are
atomic by virtue of the caller's BEGIN/COMMIT.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol, Union

import asyncpg

from authz.audit_writer import write_audit_row


DEFAULT_AUTH_CODE_TTL_MINUTES = 15
AUTH_CODE_LENGTH = 12  # base32 characters; ~60 bits of entropy


# ──────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────


class ChannelError(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class AuthCodeNotFound(ChannelError):
    def __init__(self, code: str) -> None:
        super().__init__("auth_code_not_found", f"code={code!r}")


class AuthCodeNotConsumable(ChannelError):
    def __init__(self, status: str) -> None:
        super().__init__(
            "auth_code_not_consumable", f"current_status={status!r}"
        )


class AuthCodeExpired(ChannelError):
    def __init__(self) -> None:
        super().__init__("auth_code_expired", "code is past expires_at")


# ──────────────────────────────────────────────────────────────────────
# Auth code lifecycle
# ──────────────────────────────────────────────────────────────────────


def _generate_code() -> str:
    """Base32 with O/I/0/1 stripped — operator-readable + dictation-safe."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(AUTH_CODE_LENGTH))


@dataclass(frozen=True)
class IssuedAuthCode:
    id: str
    code: str
    expires_at: datetime


async def issue_auth_code(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    issued_by_user_id: str,
    channel_kind: str,
    ttl_minutes: int = DEFAULT_AUTH_CODE_TTL_MINUTES,
) -> IssuedAuthCode:
    """Generate + persist a fresh code; emit `channel_auth_code.issued`."""
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    # Retry once on the (unlikely) collision against the global UNIQUE on `code`.
    for _ in range(3):
        code = _generate_code()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO channel_auth_codes
                  (client_id, code, channel_kind, issued_by_user_id,
                   expires_at)
                VALUES ($1::uuid, $2, $3::channel_kind, $4::uuid, $5)
                RETURNING id::text AS id, expires_at
                """,
                client_id,
                code,
                channel_kind,
                issued_by_user_id,
                expires,
            )
            break
        except asyncpg.UniqueViolationError:
            continue
    else:
        raise ChannelError(
            "auth_code_collision",
            "exhausted retries generating a unique code",
        )

    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=issued_by_user_id,
        event="channel_auth_code.issued",
        target_type="channel_auth_code",
        target_id=row["id"],
        metadata={
            "channelKind": channel_kind,
            "expiresAt": row["expires_at"].isoformat(),
            "ttlMinutes": ttl_minutes,
        },
    )
    return IssuedAuthCode(id=row["id"], code=code, expires_at=row["expires_at"])


@dataclass(frozen=True)
class BoundIdentity:
    identity_id: str
    auth_code_id: str
    user_id: str
    client_id: str


async def consume_auth_code_and_bind(
    conn: asyncpg.Connection,
    *,
    code: str,
    channel_kind: str,
    external_id: str,
) -> BoundIdentity:
    """Look up `code`; verify pending + unexpired; mark consumed; insert
    a `channel_identities` row. Emits `channel_identity.bound` audit.

    Runs cross-tenant: the bot doesn't know the tenant until it has
    consumed the code. The caller must execute on a bypass connection
    (RLS off) or a connection scoped to the right tenant.
    """
    row = await conn.fetchrow(
        """
        SELECT id::text                AS id,
               client_id::text         AS client_id,
               channel_kind::text      AS channel_kind,
               issued_by_user_id::text AS issued_by_user_id,
               status::text            AS status,
               expires_at,
               consumed_external_id
          FROM channel_auth_codes
         WHERE code = $1
        """,
        code,
    )
    if row is None:
        raise AuthCodeNotFound(code)
    if row["status"] != "pending":
        raise AuthCodeNotConsumable(row["status"])
    if row["channel_kind"] != channel_kind:
        raise ChannelError(
            "auth_code_wrong_kind",
            f"code is for {row['channel_kind']!r}, got {channel_kind!r}",
        )
    if row["expires_at"] < datetime.now(timezone.utc):
        # Best-effort mark expired so future lookups distinguish.
        # lint:bypass-rls-explain="auth code consumption is intentionally cross-tenant — the bot doesn't know the tenant until after the code is consumed; PK lookup + (channel_kind match + status='pending' guard) is the security boundary"
        await conn.execute(
            """
            UPDATE channel_auth_codes SET status = 'expired'
             WHERE id = $1::uuid AND status = 'pending'
            """,
            row["id"],
        )
        raise AuthCodeExpired()

    # Mark code consumed. The (channel_kind, external_id) pair gets
    # remembered so we can replay traceability if needed.
    # lint:bypass-rls-explain="auth code consumption is intentionally cross-tenant — same rationale as the expiry path above; PK + status guard"
    await conn.execute(
        """
        UPDATE channel_auth_codes
           SET status = 'consumed',
               consumed_external_id = $2,
               consumed_at = now()
         WHERE id = $1::uuid
        """,
        row["id"],
        external_id,
    )

    # Insert (or revive) the identity binding.
    identity_id = await conn.fetchval(
        """
        INSERT INTO channel_identities
          (client_id, channel_kind, external_id, user_id, status,
           bound_at, last_seen_at)
        VALUES ($1::uuid, $2::channel_kind, $3, $4::uuid, 'active',
                now(), now())
        ON CONFLICT (client_id, channel_kind, external_id)
        DO UPDATE SET status = 'active', user_id = EXCLUDED.user_id,
                      bound_at = now(), revoked_at = NULL,
                      updated_at = now()
        RETURNING id::text
        """,
        row["client_id"],
        channel_kind,
        external_id,
        row["issued_by_user_id"],
    )

    await write_audit_row(
        conn,
        client_id=row["client_id"],
        actor_user_id=row["issued_by_user_id"],
        event="channel_identity.bound",
        target_type="channel_identity",
        target_id=identity_id,
        metadata={
            "channelKind": channel_kind,
            "externalId": external_id,
            "authCodeId": row["id"],
        },
    )
    return BoundIdentity(
        identity_id=identity_id,
        auth_code_id=row["id"],
        user_id=row["issued_by_user_id"],
        client_id=row["client_id"],
    )


# ──────────────────────────────────────────────────────────────────────
# Identity lookup (used per-inbound to authenticate the principal)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChannelIdentityRow:
    id: str
    client_id: str
    channel_kind: str
    external_id: str
    user_id: str
    status: str


async def find_active_identity(
    conn: asyncpg.Connection,
    *,
    channel_kind: str,
    external_id: str,
) -> Optional[ChannelIdentityRow]:
    """Cross-tenant lookup. Caller is the channel adapter polling/
    webhook handler — it doesn't yet know which tenant a chat_id maps
    to. Returns None for unbound external_ids; the adapter then
    surfaces an "/start CODE-please" reply to the user."""
    row = await conn.fetchrow(
        """
        SELECT id::text         AS id,
               client_id::text  AS client_id,
               channel_kind::text AS channel_kind,
               external_id,
               user_id::text    AS user_id,
               status::text     AS status
          FROM channel_identities
         WHERE channel_kind = $1::channel_kind
           AND external_id = $2
           AND status = 'active'
         ORDER BY bound_at DESC
         LIMIT 1
        """,
        channel_kind,
        external_id,
    )
    if row is None:
        return None
    return ChannelIdentityRow(
        id=row["id"],
        client_id=row["client_id"],
        channel_kind=row["channel_kind"],
        external_id=row["external_id"],
        user_id=row["user_id"],
        status=row["status"],
    )


# ──────────────────────────────────────────────────────────────────────
# Inbound message lifecycle
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InboundMessageRow:
    id: str
    client_id: str
    intent: Optional[str]


async def record_inbound_message(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    channel_kind: str,
    channel_identity_id: Optional[str],
    external_message_id: Optional[str],
    external_chat_id: Optional[str],
    payload: dict,
    intent: Optional[str],
    actor_user_id: Optional[str],
    correlation_id: Optional[str] = None,
) -> InboundMessageRow:
    """Persist an inbound message + emit `channel_message.received`."""
    row = await conn.fetchrow(
        """
        INSERT INTO channel_messages
          (client_id, channel_kind, direction, channel_identity_id,
           external_message_id, external_chat_id, payload, intent,
           status, correlation_id)
        VALUES ($1::uuid, $2::channel_kind, 'inbound'::channel_message_direction,
                $3::uuid, $4, $5, $6::jsonb, $7,
                'received'::channel_message_status, $8)
        ON CONFLICT (channel_kind, external_message_id)
        DO UPDATE SET attempts = channel_messages.attempts + 1,
                      payload = EXCLUDED.payload
        RETURNING id::text AS id, intent
        """,
        client_id,
        channel_kind,
        channel_identity_id,
        external_message_id,
        external_chat_id,
        json.dumps(payload),
        intent,
        correlation_id,
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="channel_message.received",
        target_type="channel_message",
        target_id=row["id"],
        metadata={
            "channelKind": channel_kind,
            "intent": intent,
            "externalChatId": external_chat_id,
            "externalMessageId": external_message_id,
        },
    )
    return InboundMessageRow(
        id=row["id"], client_id=client_id, intent=row["intent"]
    )


async def mark_inbound_processed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    message_id: str,
    actor_user_id: Optional[str],
    related_work_order_id: Optional[str] = None,
    related_workflow_execution_id: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        UPDATE channel_messages
           SET status = 'processed'::channel_message_status,
               processed_at = now(),
               related_work_order_id = COALESCE($3::uuid, related_work_order_id),
               related_workflow_execution_id = COALESCE($4::uuid,
                 related_workflow_execution_id)
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        message_id,
        client_id,
        related_work_order_id,
        related_workflow_execution_id,
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="channel_message.processed",
        target_type="channel_message",
        target_id=message_id,
        metadata={
            "relatedWorkOrderId": related_work_order_id,
            "relatedWorkflowExecutionId": related_workflow_execution_id,
        },
    )


async def mark_inbound_failed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    message_id: str,
    actor_user_id: Optional[str],
    error_detail: str,
) -> None:
    await conn.execute(
        """
        UPDATE channel_messages
           SET status = 'failed'::channel_message_status,
               error_detail = $3
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        message_id,
        client_id,
        error_detail[:1000],
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="channel_message.failed",
        target_type="channel_message",
        target_id=message_id,
        metadata={"errorDetail": error_detail[:200]},
    )


# ──────────────────────────────────────────────────────────────────────
# Outbound (outbox) lifecycle
# ──────────────────────────────────────────────────────────────────────


async def queue_outbound_message(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    channel_kind: str,
    channel_identity_id: Optional[str],
    external_chat_id: str,
    payload: dict,
    idempotency_key: str,
    actor_user_id: Optional[str],
    related_work_order_id: Optional[str] = None,
    related_workflow_execution_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> str:
    """Persist outbound row in `pending` status (= the outbox queue).
    Idempotent on (channel_kind, idempotency_key) — re-queueing the
    same key is a no-op that returns the existing id."""
    existing = await conn.fetchval(
        """
        SELECT id::text FROM channel_messages
         WHERE channel_kind = $1::channel_kind
           AND idempotency_key = $2 AND client_id = $3::uuid
        """,
        channel_kind,
        idempotency_key,
        client_id,
    )
    if existing:
        return existing
    row_id = await conn.fetchval(
        """
        INSERT INTO channel_messages
          (client_id, channel_kind, direction, channel_identity_id,
           external_chat_id, payload, idempotency_key,
           status, related_work_order_id,
           related_workflow_execution_id, correlation_id)
        VALUES ($1::uuid, $2::channel_kind, 'outbound'::channel_message_direction,
                $3::uuid, $4, $5::jsonb, $6,
                'pending'::channel_message_status, $7::uuid,
                $8::uuid, $9)
        RETURNING id::text
        """,
        client_id,
        channel_kind,
        channel_identity_id,
        external_chat_id,
        json.dumps(payload),
        idempotency_key,
        related_work_order_id,
        related_workflow_execution_id,
        correlation_id,
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="channel_message.send_queued",
        target_type="channel_message",
        target_id=row_id,
        metadata={
            "channelKind": channel_kind,
            "externalChatId": external_chat_id,
            "idempotencyKey": idempotency_key,
        },
    )
    return row_id


async def mark_outbound_sent(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    message_id: str,
    actor_user_id: Optional[str],
    external_message_id: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        UPDATE channel_messages
           SET status = 'sent'::channel_message_status,
               sent_at = now(),
               external_message_id = COALESCE($3,
                 external_message_id),
               attempts = attempts + 1
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        message_id,
        client_id,
        external_message_id,
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="channel_message.sent",
        target_type="channel_message",
        target_id=message_id,
        metadata={"externalMessageId": external_message_id},
    )


async def mark_outbound_attempt_failed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    message_id: str,
    actor_user_id: Optional[str],
    error_detail: str,
    permanent: bool = False,
) -> None:
    await conn.execute(
        """
        UPDATE channel_messages
           SET status = CASE WHEN $4 THEN 'failed'::channel_message_status
                              ELSE status END,
               attempts = attempts + 1,
               error_detail = $3
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        message_id,
        client_id,
        error_detail[:1000],
        permanent,
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="channel_message.failed",
        target_type="channel_message",
        target_id=message_id,
        metadata={
            "errorDetail": error_detail[:200],
            "permanent": permanent,
        },
    )


# ──────────────────────────────────────────────────────────────────────
# ChannelAdapter Protocol — the shape every adapter implements
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InboundEvent:
    """Normalized inbound event, adapter-agnostic. Telegram / Slack /
    future adapters parse their native payload into this shape."""

    channel_kind: str
    external_chat_id: str
    external_message_id: Optional[str]
    text: str
    raw_payload: dict


class ChannelAdapter(Protocol):
    """Public Protocol for an adapter implementation. α.6 implements
    `TelegramAdapter` against this shape; α.6+ Sandbox / Slack land
    here without runtime reshape."""

    channel_kind: str

    async def fetch_inbound_batch(self) -> list[InboundEvent]:
        """Fetch zero-or-more new inbound events. Long-polling or
        webhook-buffered adapters return what they have."""
        ...

    async def deliver_outbound(
        self,
        *,
        external_chat_id: str,
        payload: dict,
    ) -> str:
        """Deliver one outbound message. Returns the channel-side
        message id (or empty string if the channel doesn't expose one).
        Raises on transient or permanent failure; caller decides retry."""
        ...
