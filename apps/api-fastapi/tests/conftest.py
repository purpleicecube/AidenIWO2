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

import pytest


# Set BEFORE main is imported anywhere downstream.
os.environ.setdefault("IWO3_POLL_WORKER_DISABLED", "true")
# Pre-Beta β.4 — same posture for the Telegram worker. Without this,
# every TestClient(app) would start the polling loop and try to hit
# Telegram with whatever stale env vars happen to be set.
os.environ.setdefault("IWO3_TELEGRAM_WORKER_DISABLED", "true")
# Beta-2 phase 0.2 — auto-dispatch worker. Same discipline: keep the
# 30s-tick worker out of pytest TestClient lifespans so it doesn't
# move pending → processing on rows other tests are exercising.
os.environ.setdefault("IWO3_WO_DISPATCH_WORKER_DISABLED", "true")
# BUG-067 — workflow step auto-advance worker. Same posture: keep
# the 10s-tick worker out of pytest TestClient lifespans so it
# doesn't advance step_runs other tests are exercising.
os.environ.setdefault("IWO3_WORKFLOW_STEP_WORKER_DISABLED", "true")


# ── Live-database guard (BUG: Klear Gamma credential, 2026-09-05) ────
#
# `tests/test_poll_registry.py::_seed_gamma_credential` runs, verbatim:
#
#     DELETE FROM adapter_credentials WHERE client_id = <Klear> ...
#     INSERT ... 'credential_ref:env:GAMMA_REGISTRY_TEST_KEY' ...
#
# with no teardown restoring the original. On 2026-05-19 that ran
# against the OPERATOR'S database rather than the disposable one. It
# destroyed Klear's real Gamma credential — the one BUG-069 had
# repaired three days earlier — and replaced it with a fixture value
# naming an env var that exists nowhere. Every Gamma render since
# failed with `credential_missing: env var GAMMA_REGISTRY_TEST_KEY is
# not set or empty`, and the row's created_at (2026-05-19 00:46:30,
# never updated, no notes) is the fingerprint.
#
# The vitest lane already refuses this: `infra/local/test-integration-iwo3.sh`
# enforces three guards, including "test DB name must end in _test".
# The pytest lane had none — `IWO3_DATABASE_URL=<live> pytest tests/`
# just ran. This is that missing guard.
#
# Deliberately blunt: refuse the whole session rather than try to sort
# read-only tests from destructive ones. A test suite that can silently
# eat production data is not worth the convenience of skipping a two-
# word env var. `IWO3_ALLOW_NON_TEST_DB=true` is the explicit override
# for the rare deliberate case.

_ALLOW_NON_TEST_DB = "IWO3_ALLOW_NON_TEST_DB"


def _database_name(url: str) -> str:
    """Last path segment of a Postgres URL, minus any query string."""
    tail = url.rsplit("/", 1)[-1] if "/" in url else ""
    return tail.split("?", 1)[0].strip()


def pytest_configure(config) -> None:  # noqa: ANN001
    url = os.environ.get("IWO3_DATABASE_URL", "").strip()
    if not url:
        # No DB configured — DB-backed tests skip themselves. Fine.
        return
    if os.environ.get(_ALLOW_NON_TEST_DB, "").lower() in {"true", "1", "yes"}:
        return
    name = _database_name(url)
    if name.endswith("_test"):
        return
    raise pytest.UsageError(
        "\n"
        "REFUSING TO RUN: IWO3_DATABASE_URL points at a database named\n"
        f"  '{name}' — which does not end in '_test'.\n\n"
        "Fixtures in this suite DELETE and rewrite real tenant rows "
        "(adapter_credentials,\nwork_orders, handoffs) with no teardown. "
        "Running them against an operator\ndatabase destroys live "
        "configuration — it already did once, on 2026-05-19,\n"
        "taking out Klear's Gamma credential.\n\n"
        "Use the disposable lane instead:\n"
        "  IWO3_DATABASE_URL=$IWO3_TEST_DATABASE_URL pytest tests/\n"
        "  # or the full wrapper:  npm run test:integration\n\n"
        f"If you genuinely mean to target '{name}', set "
        f"{_ALLOW_NON_TEST_DB}=true.\n"
    )
