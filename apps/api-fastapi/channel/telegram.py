"""MegaLoop Alpha α.6 — Telegram adapter.

Implements ChannelAdapter against the Telegram Bot API. Per-tenant
bot tokens via credential_ref:env:TELEGRAM_BOT_TOKEN_<TENANT> (Stage
A § B4). Long-poll worker for inbound (no public webhook needed in
Alpha). Outbox-driven outbound via deliver_outbound().

Intent parsing is regex-based for Alpha. Matches Stage A § B2
mandatory action set:
  - /start CODE                    bind identity (Stage A § B7)
  - /status WO_ID                  read WO status
  - create wo: TITLE   |  /create_wo TITLE   create WO
  - /approve WO_ID                 transition processing → completed
  - /reopen WO_ID                  transition (any) → pending via reopen cycle
  - /unblock WO_ID                 transition blocked → processing

For Alpha simplicity, /start binding is the only intent that runs
WITHOUT a pre-bound channel_identity. All other intents require the
chat_id to be bound; unbound chats get a friendly "/start CODE"
prompt back.

RBAC: every intent enforces the bound user's permissions via
checkPermission. Insufficient permission → friendly Telegram reply
+ authz.denied audit row (FastAPI dispatcher gates).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import httpx


TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_LONG_POLL_TIMEOUT_SECONDS = 25  # bot API supports up to 50


@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    message_id: Optional[int]
    chat_id: str
    text: str
    raw: dict


class TelegramApiError(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def env_var_for_telegram_bot_token(client_designation: str) -> str:
    """Map IWO | Klear.ai → TELEGRAM_BOT_TOKEN_KLEAR. Best-effort
    sanitization; non-alphanumeric chars get squashed to underscore."""
    short = (
        client_designation.split("|")[-1].strip()
        if "|" in client_designation
        else client_designation
    )
    short = re.sub(r"[^A-Za-z0-9]+", "_", short).strip("_").upper()
    return f"TELEGRAM_BOT_TOKEN_{short}"


def resolve_bot_token(*, env_var: str, env=None) -> str:
    env_map = env if env is not None else os.environ
    val = env_map.get(env_var)
    if not val:
        raise TelegramApiError(
            "credential_missing", f"env var {env_var} not set or empty"
        )
    return val


def build_get_updates_url(token: str) -> str:
    return f"{TELEGRAM_API_BASE}/bot{token}/getUpdates"


def build_send_message_url(token: str) -> str:
    return f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"


def parse_telegram_update(raw: dict) -> Optional[TelegramUpdate]:
    """Extract the fields we care about from a Telegram Update object.
    Returns None for updates we don't handle (e.g. callback queries —
    Alpha is text-only)."""
    if not isinstance(raw, dict):
        return None
    update_id = raw.get("update_id")
    if not isinstance(update_id, int):
        return None
    msg = raw.get("message")
    if not isinstance(msg, dict):
        return None
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    text = msg.get("text")
    if not isinstance(text, str):
        return None
    return TelegramUpdate(
        update_id=update_id,
        message_id=msg.get("message_id"),
        chat_id=str(chat_id),
        text=text,
        raw=raw,
    )


# ──────────────────────────────────────────────────────────────────────
# Intent parser — pure, no DB. Used by tests + dispatcher.
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedIntent:
    intent: str  # "start" | "status" | "create_wo" | "approve" | "reopen" | "unblock" | "unknown"
    arg: Optional[str]


_RE_START = re.compile(r"^/start\s+(\S+)\s*$", re.IGNORECASE)
_RE_STATUS = re.compile(r"^/status\s+(\S+)\s*$", re.IGNORECASE)
_RE_CREATE_WO_SLASH = re.compile(r"^/create_wo\s+(.+)$", re.IGNORECASE | re.DOTALL)
_RE_CREATE_WO_NL = re.compile(r"^create\s+wo:\s*(.+)$", re.IGNORECASE | re.DOTALL)
_RE_APPROVE = re.compile(r"^/approve\s+(\S+)\s*$", re.IGNORECASE)
_RE_REOPEN = re.compile(r"^/reopen\s+(\S+)\s*$", re.IGNORECASE)
_RE_UNBLOCK = re.compile(r"^/unblock\s+(\S+)\s*$", re.IGNORECASE)


def parse_intent(text: str) -> ParsedIntent:
    body = text.strip()
    m = _RE_START.match(body)
    if m:
        return ParsedIntent("start", m.group(1).strip())
    m = _RE_STATUS.match(body)
    if m:
        return ParsedIntent("status", m.group(1).strip())
    m = _RE_CREATE_WO_SLASH.match(body)
    if m:
        return ParsedIntent("create_wo", m.group(1).strip())
    m = _RE_CREATE_WO_NL.match(body)
    if m:
        return ParsedIntent("create_wo", m.group(1).strip())
    m = _RE_APPROVE.match(body)
    if m:
        return ParsedIntent("approve", m.group(1).strip())
    m = _RE_REOPEN.match(body)
    if m:
        return ParsedIntent("reopen", m.group(1).strip())
    m = _RE_UNBLOCK.match(body)
    if m:
        return ParsedIntent("unblock", m.group(1).strip())
    return ParsedIntent("unknown", body[:200] if body else None)


# ──────────────────────────────────────────────────────────────────────
# TelegramAdapter — implements channel.core.ChannelAdapter Protocol
# ──────────────────────────────────────────────────────────────────────


class TelegramAdapter:
    """Per-tenant Telegram adapter. One instance per tenant; the
    polling worker iterates over all configured tenants and calls
    fetch_inbound_batch on each."""

    channel_kind = "telegram"

    def __init__(
        self,
        *,
        client_id: str,
        env_var: str,
        env=None,
        fetch_transport: Optional[httpx.BaseTransport] = None,
        send_transport: Optional[httpx.BaseTransport] = None,
        api_base: str = TELEGRAM_API_BASE,
        timeout_seconds: float = 30.0,
        long_poll_seconds: int = TELEGRAM_LONG_POLL_TIMEOUT_SECONDS,
    ) -> None:
        self.client_id = client_id
        self.env_var = env_var
        self._env = env if env is not None else os.environ
        self._fetch_transport = fetch_transport
        self._send_transport = send_transport
        self._api_base = api_base
        self._timeout = timeout_seconds
        self._long_poll = long_poll_seconds
        # Persisted by the worker between ticks via offset_storage.
        self._next_offset: Optional[int] = None

    def set_offset(self, offset: int) -> None:
        self._next_offset = offset

    @property
    def next_offset(self) -> Optional[int]:
        return self._next_offset

    def _bot_token(self) -> str:
        return resolve_bot_token(env_var=self.env_var, env=self._env)

    async def fetch_inbound_batch(self) -> list[TelegramUpdate]:
        """One getUpdates call. Returns parsed updates and advances
        next_offset. Caller decides cadence (worker tick or webhook)."""
        token = self._bot_token()
        url = build_get_updates_url(token)
        params = {"timeout": str(self._long_poll)}
        if self._next_offset is not None:
            params["offset"] = str(self._next_offset)

        try:
            with httpx.Client(
                timeout=self._timeout + self._long_poll,
                transport=self._fetch_transport,
            ) as cli:
                resp = cli.get(url, params=params)
        except httpx.HTTPError as exc:
            raise TelegramApiError("network_error", str(exc))

        if resp.status_code != 200:
            raise TelegramApiError(
                "http_error",
                f"status={resp.status_code} body={resp.text[:300]!r}",
            )
        data = resp.json()
        if not data.get("ok"):
            raise TelegramApiError(
                "api_error", json.dumps(data)[:300]
            )

        updates: list[TelegramUpdate] = []
        max_id = self._next_offset or 0
        for raw in data.get("result", []):
            parsed = parse_telegram_update(raw)
            if parsed is None:
                # Still advance the offset to consume the unhandled update.
                if isinstance(raw, dict) and isinstance(raw.get("update_id"), int):
                    max_id = max(max_id, raw["update_id"])
                continue
            updates.append(parsed)
            max_id = max(max_id, parsed.update_id)
        if updates or max_id:
            self._next_offset = max_id + 1
        return updates

    async def deliver_outbound(
        self,
        *,
        external_chat_id: str,
        payload: dict,
    ) -> str:
        """Send one message to Telegram. Returns the message_id Telegram
        assigned (string) for the channel_messages.external_message_id
        column. Raises TelegramApiError on failure (caller decides
        retry vs permanent)."""
        token = self._bot_token()
        url = build_send_message_url(token)
        body = {
            "chat_id": external_chat_id,
            "text": payload.get("text", ""),
        }
        if "parse_mode" in payload:
            body["parse_mode"] = payload["parse_mode"]
        if "reply_to_message_id" in payload:
            body["reply_to_message_id"] = payload["reply_to_message_id"]

        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._send_transport,
            ) as cli:
                resp = cli.post(url, json=body)
        except httpx.HTTPError as exc:
            raise TelegramApiError("network_error", str(exc))

        if resp.status_code != 200:
            raise TelegramApiError(
                "http_error",
                f"status={resp.status_code} body={resp.text[:300]!r}",
            )
        data = resp.json()
        if not data.get("ok"):
            raise TelegramApiError(
                "api_error", json.dumps(data)[:300]
            )
        result = data.get("result") or {}
        mid = result.get("message_id")
        return str(mid) if mid is not None else ""
