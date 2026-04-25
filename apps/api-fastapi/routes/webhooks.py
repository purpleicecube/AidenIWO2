"""MegaLoop Beta-1 ε.4 + Beta-1.5 ε.5 / Q3 — channel webhook ingress.

Architect Q3 lock: HMAC-signed webhook is the canonical production
path; long-poll worker stays as fallback for dev/offline. Beta-1.5
ε.5 closes two architect-flagged gaps:
  HIGH — verified payloads MUST enter the same dispatch pipeline as
         the long-poll worker (workers.telegram_worker.
         process_telegram_update). Without this, an operator who
         disables the worker for production loses inbound processing.
  MED  — webhook.signature_invalid audit MUST be emitted on every
         401 path (the locked event was inert prior to ε.5).

Routes:
  POST /webhook/telegram     verify HMAC → tenant resolution → dispatch
  POST /webhook/slack        Beta-2 placeholder (503)

HMAC verification (unchanged from ε.4):
  Per-tenant secret in IWO3_WEBHOOK_HMAC_<TENANT> env var (mirrors
  α.6 TELEGRAM_BOT_TOKEN_<TENANT> pattern). Two signature paths:
    (a) X-IWO3-Webhook-Signature: sha256=<hex> + optional
        X-IWO3-Webhook-Timestamp (5-min replay window)
    (b) X-Telegram-Bot-Api-Secret-Token literal-string compare
  Constant-time compare via hmac.compare_digest.

Audit (locked under BETA_PHASE_1_AUDIT_EVENTS in ε.1):
  webhook.received           on successful verification
  webhook.signature_invalid  on every 401 path; one row per
                             configured tenant we tested against so
                             operators see attack pressure per-tenant.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from authz.audit_writer import write_audit_row
from channel.telegram import (
    TelegramAdapter,
    env_var_for_telegram_bot_token,
    parse_telegram_update,
)
from deps import get_db_pool
from workers.telegram_worker import process_telegram_update


router = APIRouter(prefix="/webhook", tags=["webhooks"])

log = logging.getLogger("iwo3.webhooks")


_TIMESTAMP_WINDOW_SECONDS = 300  # 5 min replay window
_HMAC_ENV_PREFIX = "IWO3_WEBHOOK_HMAC_"


class WebhookAck(BaseModel):
    ok: bool
    detail: str = ""


def _hmac_env_name(designation: str) -> str:
    """Per-tenant HMAC secret env var name. Mirrors the
    Telegram-token resolution pattern from α.6 (Stage A § B4)."""
    suffix = env_var_for_telegram_bot_token(designation)
    if suffix.startswith("TELEGRAM_BOT_TOKEN_"):
        tenant_part = suffix[len("TELEGRAM_BOT_TOKEN_"):]
    else:
        tenant_part = suffix
    return _HMAC_ENV_PREFIX + tenant_part


def _resolve_webhook_secret(designation: str) -> Optional[str]:
    return os.environ.get(_hmac_env_name(designation))


def _signature_matches(
    *,
    secret: str,
    raw_body: bytes,
    signature_header: Optional[str],
    timestamp_header: Optional[str],
    secret_token_header: Optional[str],
) -> tuple[bool, str]:
    """Returns (matches, path_label). path_label is `hmac` |
    `telegram_native` | `none` for the audit metadata."""
    # Path A — generic HMAC
    if signature_header and signature_header.startswith("sha256="):
        if timestamp_header:
            try:
                ts = int(timestamp_header)
            except (TypeError, ValueError):
                return (False, "hmac_bad_timestamp")
            if abs(int(time.time()) - ts) > _TIMESTAMP_WINDOW_SECONDS:
                return (False, "hmac_expired_timestamp")
            signed_input = f"{ts}.".encode("ascii") + raw_body
        else:
            signed_input = raw_body
        expected = hmac.new(
            secret.encode("utf-8"), signed_input, hashlib.sha256
        ).hexdigest()
        actual = signature_header[len("sha256="):]
        if hmac.compare_digest(actual, expected):
            return (True, "hmac")
        return (False, "hmac_bad_sig")
    # Path B — Telegram native (literal-string compare)
    if secret_token_header and hmac.compare_digest(
        secret_token_header, secret
    ):
        return (True, "telegram_native")
    return (False, "none")


async def _resolve_tenant_and_audit(
    *,
    raw_body: bytes,
    signature_header: Optional[str],
    timestamp_header: Optional[str],
    secret_token_header: Optional[str],
) -> tuple[str, str]:
    """Walk active tenants; return (client_id, designation) for the
    one whose webhook secret verifies. On failure, emit one
    webhook.signature_invalid audit row per configured-secret tenant
    we tested against so operators see attack pressure per-tenant.
    Then raise 401."""
    pool = get_db_pool()
    tested: list[tuple[str, str, str]] = []  # (client_id, designation, why)
    matched: Optional[tuple[str, str]] = None

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text AS client_id, designation
              FROM clients
             WHERE status = 'active'::client_status
            """
        )
        for r in rows:
            secret = _resolve_webhook_secret(r["designation"])
            if not secret:
                # No configured secret → nothing to audit; this tenant
                # simply isn't expecting webhooks.
                continue
            ok, label = _signature_matches(
                secret=secret,
                raw_body=raw_body,
                signature_header=signature_header,
                timestamp_header=timestamp_header,
                secret_token_header=secret_token_header,
            )
            if ok:
                matched = (r["client_id"], r["designation"])
                break
            tested.append((r["client_id"], r["designation"], label))

        if matched is not None:
            return matched

        # 401 path — emit per-tenant signature_invalid audits.
        for client_id, designation, why in tested:
            try:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT set_config('app.current_client_id', $1, true)",
                        client_id,
                    )
                    await conn.execute("SET LOCAL ROLE iwo3_app")
                    await write_audit_row(
                        conn,
                        client_id=client_id,
                        actor_user_id=None,
                        event="webhook.signature_invalid",
                        target_type="webhook",
                        target_id=None,
                        metadata={
                            "channel": "telegram",
                            "tenant_designation": designation,
                            "why": why,
                            "body_bytes": len(raw_body),
                            "had_hmac_header": bool(signature_header),
                            "had_telegram_header": bool(secret_token_header),
                        },
                    )
            except Exception as exc:  # noqa: BLE001 — audit best-effort
                log.warning(
                    "webhooks: signature_invalid audit failed for "
                    "tenant=%s: %s",
                    designation,
                    exc,
                )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "webhook_signature_invalid"},
    )


async def _emit_received(client_id: str, *, metadata: dict[str, Any]) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_client_id', $1, true)",
                client_id,
            )
            await conn.execute("SET LOCAL ROLE iwo3_app")
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=None,
                event="webhook.received",
                target_type="webhook",
                target_id=None,
                metadata=metadata,
            )


@router.post("/telegram", response_model=WebhookAck)
async def receive_telegram_webhook(
    request: Request,
    x_iwo3_webhook_signature: Annotated[
        Optional[str], Header(alias="X-IWO3-Webhook-Signature")
    ] = None,
    x_iwo3_webhook_timestamp: Annotated[
        Optional[str], Header(alias="X-IWO3-Webhook-Timestamp")
    ] = None,
    x_telegram_bot_api_secret_token: Annotated[
        Optional[str], Header(alias="X-Telegram-Bot-Api-Secret-Token")
    ] = None,
) -> WebhookAck:
    """Verify HMAC → resolve tenant → dispatch through the same
    pipeline as the long-poll worker (Beta-1.5 ε.5 architect fix)."""
    raw = await request.body()

    client_id, designation = await _resolve_tenant_and_audit(
        raw_body=raw,
        signature_header=x_iwo3_webhook_signature,
        timestamp_header=x_iwo3_webhook_timestamp,
        secret_token_header=x_telegram_bot_api_secret_token,
    )

    # Parse + dispatch. Audit failures here go to the inbound failed
    # path inside process_telegram_update; the webhook layer just
    # records `webhook.received` with the parse outcome.
    parsed = None
    parse_ok = False
    try:
        payload = json.loads(raw.decode("utf-8"))
        parsed = parse_telegram_update(payload)
        parse_ok = parsed is not None
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "webhooks: telegram body parse failed tenant=%s: %s",
            designation,
            exc,
        )

    await _emit_received(
        client_id,
        metadata={
            "channel": "telegram",
            "tenant_designation": designation,
            "signature_path": (
                "hmac"
                if x_iwo3_webhook_signature
                else "telegram_native"
            ),
            "body_bytes": len(raw),
            "parsed": parse_ok,
        },
    )

    if parsed is not None:
        # Construct a per-request TelegramAdapter and hand off to the
        # shared worker pipeline. Failures inside the pipeline land in
        # channel_messages with `failed` status — we don't 5xx the
        # webhook because the inbound is durably persisted.
        var_name = env_var_for_telegram_bot_token(designation)
        adapter = TelegramAdapter(
            client_id=client_id,
            env_var=var_name,
        )
        try:
            await process_telegram_update(
                get_db_pool(), adapter, parsed
            )
        except Exception as exc:  # noqa: BLE001 — webhook boundary
            log.exception(
                "webhooks: dispatch failed tenant=%s update=%s: %s",
                designation,
                parsed.update_id,
                exc,
            )
            # The inbound is recorded inside record_inbound_message;
            # process_telegram_update writes mark_inbound_failed on
            # exceptions. We still return 200 so Telegram doesn't
            # retry — duplicate retries are idempotent at the
            # inbound UNIQUE level (β.5 hardening).

    return WebhookAck(
        ok=True,
        detail=(
            f"verified_for_tenant={designation};"
            f" parsed={'yes' if parse_ok else 'no'};"
            f" dispatched={'yes' if parsed is not None else 'no'}"
        ),
    )


@router.post("/slack", response_model=WebhookAck)
async def receive_slack_webhook(request: Request) -> WebhookAck:
    """Beta-2 surface — included at Beta-1 closeout so the URL exists
    + HMAC posture is documented. Returns 503 until the Slack
    adapter ships in Beta-2."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "slack_webhook_pending_beta_2",
            "message": (
                "Slack webhook ingress shape is locked at Beta-1 "
                "closeout but the adapter ships in Beta-2."
            ),
        },
    )
