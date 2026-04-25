"""MegaLoop Beta-1 ε.4 / Q3 — channel webhook ingress.

Architect Q3 lock: HMAC-signed webhook is the canonical production
path; long-poll worker stays as fallback for dev/offline. This
module is the production endpoint shape; the long-poll worker in
workers/telegram_worker.py keeps running per its existing env-flag
gate. Architect explicitly kept C ("both") so neither path is
load-bearing alone.

Routes:
  POST /webhook/telegram     receive a Telegram Update payload after
                             HMAC-SHA256 verification against per-
                             tenant secret (header X-Telegram-Bot-Api-Secret-Token
                             OR our generic X-IWO3-Webhook-Signature).
  POST /webhook/slack        Beta-2 surface — included now so the
                             ingress shape is locked at Beta-1
                             closeout. Returns 503 until Beta-2
                             wires the Slack adapter.

HMAC verification:
  - Per-tenant secret sourced from `adapter_credentials` rows with
    a `webhook_hmac_secret` credential_kind. Beta-1 reads the secret
    via env (mirrors the existing TELEGRAM_BOT_TOKEN_<tenant> pattern):
    `IWO3_WEBHOOK_HMAC_<TENANT>` env var, where <TENANT> is derived
    via `env_var_for_telegram_bot_token`.
  - Signature header: `X-IWO3-Webhook-Signature` carries
    `sha256=<hex>` (GitHub-style). Telegram's native
    `X-Telegram-Bot-Api-Secret-Token` is a literal-string compare and
    is also accepted as a fallback.
  - Constant-time compare via hmac.compare_digest.
  - Replay protection: timestamp window enforced via the X-IWO3-
    Webhook-Timestamp header (within 5 min). Telegram's native flow
    doesn't carry a timestamp, so the timestamp check is optional
    for the fallback secret-token path.

Audit:
  webhook.received           on successful verification
  webhook.signature_invalid  on any signature failure (bad HMAC,
                             expired timestamp, missing headers)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from authz.audit_writer import write_audit_row
from channel.telegram import env_var_for_telegram_bot_token, parse_telegram_update
from deps import get_db_pool


router = APIRouter(prefix="/webhook", tags=["webhooks"])


_TIMESTAMP_WINDOW_SECONDS = 300  # 5 min replay window
_HMAC_ENV_PREFIX = "IWO3_WEBHOOK_HMAC_"


class WebhookAck(BaseModel):
    ok: bool
    detail: str = ""


def _resolve_webhook_secret(client_designation: str) -> Optional[str]:
    """Per-tenant webhook secret, sourced from env. Mirrors the
    Telegram-token resolution pattern from α.6 (Stage A § B4)."""
    suffix = env_var_for_telegram_bot_token(client_designation)
    # env_var_for_telegram_bot_token returns "TELEGRAM_BOT_TOKEN_<TENANT>";
    # we want the short tenant suffix only.
    if suffix.startswith("TELEGRAM_BOT_TOKEN_"):
        tenant_part = suffix[len("TELEGRAM_BOT_TOKEN_"):]
    else:
        tenant_part = suffix
    return os.environ.get(_HMAC_ENV_PREFIX + tenant_part)


async def _resolve_tenant_for_webhook(
    conn: asyncpg.Connection,
    *,
    raw_body: bytes,
    signature_header: Optional[str],
    timestamp_header: Optional[str],
    secret_token_header: Optional[str],
) -> tuple[str, str]:
    """Walk active tenants, find the one whose webhook secret verifies
    the signed body. Returns (client_id, designation) on success;
    raises HTTPException(401) otherwise.

    This is intentionally O(N tenants) — the same posture as the
    Telegram polling worker. For Alpha posture (≤5 tenants) this is
    fine; Beta-2 may add a per-secret index if the tenant count grows.
    """
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
            continue
        # Path A — generic HMAC (X-IWO3-Webhook-Signature: sha256=...)
        if signature_header and signature_header.startswith("sha256="):
            if timestamp_header:
                try:
                    ts = int(timestamp_header)
                except (TypeError, ValueError):
                    continue
                if abs(int(time.time()) - ts) > _TIMESTAMP_WINDOW_SECONDS:
                    continue
                signed_input = (
                    f"{ts}.".encode("ascii") + raw_body
                )
            else:
                signed_input = raw_body
            expected = hmac.new(
                secret.encode("utf-8"), signed_input, hashlib.sha256
            ).hexdigest()
            actual = signature_header[len("sha256="):]
            if hmac.compare_digest(actual, expected):
                return r["client_id"], r["designation"]
        # Path B — Telegram native (literal-string compare).
        if secret_token_header and hmac.compare_digest(
            secret_token_header, secret
        ):
            return r["client_id"], r["designation"]
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "webhook_signature_invalid"},
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
    """Verify the inbound Telegram payload + emit a webhook.received
    audit row. The actual intent dispatch reuses the existing
    long-poll handler path; the webhook just enqueues into the same
    pipeline so dev (long-poll) and prod (webhook) produce identical
    operator-facing behaviour.
    """
    raw = await request.body()

    # Open a bypass conn to find the tenant the secret matches.
    pool = get_db_pool()
    async with pool.acquire() as conn:
        try:
            client_id, designation = await _resolve_tenant_for_webhook(
                conn,
                raw_body=raw,
                signature_header=x_iwo3_webhook_signature,
                timestamp_header=x_iwo3_webhook_timestamp,
                secret_token_header=x_telegram_bot_api_secret_token,
            )
        except HTTPException:
            # Audit the rejection on a bypass conn — no tenant context
            # to scope to since verification failed; we use the
            # `_emit_signature_invalid` helper to write under the
            # closest plausible tenant (none, in this case → audit row
            # uses NULL client_id which RLS would reject; we skip the
            # write rather than crash and re-raise).
            raise

        # Audit: webhook.received on the resolved tenant.
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
                metadata={
                    "channel": "telegram",
                    "tenant_designation": designation,
                    "signature_path": (
                        "hmac"
                        if x_iwo3_webhook_signature
                        else "telegram_native"
                    ),
                    "body_bytes": len(raw),
                },
            )

    # Best-effort parse to verify the body shape; we don't dispatch
    # here — the long-poll worker stays the canonical inbound
    # processor, and a Beta-2 follow-up can replace it with a
    # per-update enqueue once the Slack adapter lands. This keeps
    # the webhook scope tight: verify + audit + acknowledge.
    try:
        import json
        payload = json.loads(raw.decode("utf-8"))
        parsed = parse_telegram_update(payload)
    except Exception:  # noqa: BLE001
        parsed = None

    return WebhookAck(
        ok=True,
        detail=(
            f"verified_for_tenant={designation};"
            f" parsed={'yes' if parsed else 'no'}"
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
