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
