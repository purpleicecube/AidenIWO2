"""Pytest configuration for api-fastapi tests.

MegaLoop Alpha α.1 — disables the scheduled poll worker by default
inside pytest. Tests that want to exercise the worker explicitly can
unset this env var or run the worker functions directly.

Without this, every TestClient(app) construction would spin up a
30s-tick background task that mutates real handoff state across
tenants, polluting tests + leaking transactions.
"""

from __future__ import annotations

import os


# Set BEFORE main is imported anywhere downstream.
os.environ.setdefault("IWO3_POLL_WORKER_DISABLED", "true")
# Pre-Beta β.4 — same posture for the Telegram worker. Without this,
# every TestClient(app) would start the polling loop and try to hit
# Telegram with whatever stale env vars happen to be set.
os.environ.setdefault("IWO3_TELEGRAM_WORKER_DISABLED", "true")
