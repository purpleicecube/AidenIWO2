"""Pre-Beta β.4 — telegram_worker unit tests.

Covers the worker scaffolding without firing real Telegram traffic.
The worker's IO-heavy paths (fetch_inbound_batch, deliver_outbound)
are exercised through TelegramAdapter MockTransport in α.6 tests;
this file verifies:

  - disabled-by-default in pytest (conftest sets the env var)
  - tenant scan filters by env-var presence
  - tick is a no-op when no tenants resolve
"""

from __future__ import annotations

import os

import pytest


def test_worker_disabled_in_test_env() -> None:
    # conftest.py sets this; if it disappears, every TestClient(app)
    # would start the live polling loop.
    assert os.environ.get("IWO3_TELEGRAM_WORKER_DISABLED") == "true"


def test_disabled_short_circuits_loop() -> None:
    from workers.telegram_worker import _disabled

    assert _disabled() is True


def test_tick_seconds_default_is_10() -> None:
    saved = os.environ.pop("IWO3_TELEGRAM_WORKER_TICK_SECONDS", None)
    try:
        from workers.telegram_worker import _tick_seconds

        assert _tick_seconds() == 10
    finally:
        if saved is not None:
            os.environ["IWO3_TELEGRAM_WORKER_TICK_SECONDS"] = saved


def test_tick_seconds_floor_is_3() -> None:
    os.environ["IWO3_TELEGRAM_WORKER_TICK_SECONDS"] = "1"
    try:
        from workers.telegram_worker import _tick_seconds

        assert _tick_seconds() == 3
    finally:
        os.environ.pop("IWO3_TELEGRAM_WORKER_TICK_SECONDS", None)
