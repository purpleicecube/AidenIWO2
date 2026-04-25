"""MegaLoop Alpha Phase α.1 — generalized adapter poll registry.

Replaces the Loop 9 Phase 9.4 Gamma-only `poll_gamma_handoff` direct
import with an `(adapter_key) → handler` registry. Sandbox PPTX/PDF
(Beta) and any other live adapter registers its own poll handler;
the FastAPI poll route + scheduled worker always go through this
registry so they don't need to know about adapter specifics.

Dispatch semantics are identical to Phase 9.4 (Darrel §Q3):
  - WO stays in `processing` while adapter is rendering
  - Watchdog fires only on stale poll OR true terminal failure
  - Healthy long renders never double-terminalize the WO

The registry preserves Loop 9 ADR-020 §5 non-Gamma symmetry: the
public API is adapter-agnostic; Gamma is just the first registrant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Awaitable, Callable, Optional, Protocol

import asyncpg
import httpx

from adapter.gamma_poll import PollOutcome


PollHandler = Callable[..., Awaitable[PollOutcome]]


_POLL_HANDLERS: dict[str, PollHandler] = {}


def register_poll_handler(adapter_key: str, handler: PollHandler) -> None:
    """Idempotent: registering the same key twice replaces the prior entry."""
    _POLL_HANDLERS[adapter_key] = handler


def known_poll_adapter_keys() -> list[str]:
    return sorted(_POLL_HANDLERS.keys())


def __reset_for_test__() -> None:
    """Test-only — clear all registered handlers."""
    _POLL_HANDLERS.clear()


async def poll_handoff_via_registry(
    conn: asyncpg.Connection,
    *,
    handoff_id: str,
    client_id: str,
    actor_user_id: Optional[str],
    now_override: Optional[datetime] = None,
    force_stale_watchdog: bool = False,
    fetch_transport: Optional[httpx.BaseTransport] = None,
) -> PollOutcome:
    """Look up the handoff's adapter_key, dispatch to the registered
    handler, return its outcome. If the adapter isn't registered, fail
    closed with `adapter_not_found`."""
    row = await conn.fetchrow(
        """
        SELECT cat.adapter_key
          FROM output_handoffs h
     LEFT JOIN adapter_catalog cat ON cat.id = h.adapter_catalog_id
         WHERE h.id = $1 AND h.client_id = $2
        """,
        handoff_id,
        client_id,
    )
    if row is None:
        return PollOutcome(kind="handoff_not_found", handoff_id=handoff_id)
    adapter_key = row["adapter_key"]
    if not adapter_key:
        return PollOutcome(
            kind="adapter_not_found",
            handoff_id=handoff_id,
            detail="handoff has no adapter_catalog_id",
        )
    handler = _POLL_HANDLERS.get(adapter_key)
    if handler is None:
        return PollOutcome(
            kind="adapter_not_found",
            handoff_id=handoff_id,
            detail=(
                f"no poll handler registered for adapter_key={adapter_key}"
            ),
        )
    return await handler(
        conn,
        handoff_id=handoff_id,
        client_id=client_id,
        actor_user_id=actor_user_id,
        now_override=now_override,
        force_stale_watchdog=force_stale_watchdog,
        fetch_transport=fetch_transport,
    )


class PollHandlerProtocol(Protocol):
    """Type contract every adapter poll handler must satisfy."""

    async def __call__(
        self,
        conn: asyncpg.Connection,
        *,
        handoff_id: str,
        client_id: str,
        actor_user_id: Optional[str],
        now_override: Optional[datetime] = None,
        force_stale_watchdog: bool = False,
        fetch_transport: Optional[httpx.BaseTransport] = None,
    ) -> PollOutcome:
        ...
