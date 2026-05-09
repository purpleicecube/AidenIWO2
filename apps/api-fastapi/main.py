"""AIDEN IWO3 FastAPI runtime API.

Loop 7 Phase 7.1 — routers + CORS + startup/shutdown hooks.
MegaLoop Alpha α.1 — adds the scheduled poll worker as a lifespan
background task (runs every IWO3_POLL_WORKER_TICK_SECONDS, default
30s; disable with IWO3_POLL_WORKER_DISABLED=true for tests).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Register poll handlers at app-import time. Kept out of
# adapter/__init__.py so the parity CLIs (dispatch_gating_cli +
# gamma_request_shape_cli) don't transitively pull wo_wf.transitions
# into their import graph — TS/Python parity tests spawn those CLIs
# as subprocesses and need a minimal import surface.
from adapter.gamma_poll import poll_gamma_handoff
from adapter.poll_registry import register_poll_handler

register_poll_handler("gamma", poll_gamma_handoff)

from deps import get_db_pool, shutdown_db_pool, startup_db_pool
from routes import (
    adapter_credentials,
    aiden,
    audit_log,
    auth as auth_routes,
    candidate_review,
    canonical_facts as canonical_facts_routes,
    channels,
    chat_sessions,
    dispatch,
    health,
    llm,
    output_packages,
    template_profiles,
    tenants,
    tool_locker,
    tools as tools_routes,
    webhooks,
    work_orders,
    workflows,
    workspace,
)
from workers.poll_worker import poll_worker_loop
from workers.telegram_worker import telegram_worker_loop
from workers.wo_dispatch_worker import wo_dispatch_worker_loop


log = logging.getLogger("iwo3.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_db_pool()
    worker_task = asyncio.create_task(poll_worker_loop(get_db_pool()))
    telegram_task = asyncio.create_task(
        telegram_worker_loop(get_db_pool())
    )
    wo_dispatch_task = asyncio.create_task(
        wo_dispatch_worker_loop(get_db_pool())
    )
    try:
        yield
    finally:
        for t in (worker_task, telegram_task, wo_dispatch_task):
            t.cancel()
        for t, name in (
            (worker_task, "poll_worker"),
            (telegram_task, "telegram_worker"),
            (wo_dispatch_task, "wo_dispatch_worker"),
        ):
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                log.exception("%s shutdown raised: %s", name, exc)
        await shutdown_db_pool()


app = FastAPI(
    title="AIDEN IWO3 API",
    version="0.1.0",
    description="IWO3 runtime API — Loop 7 Phase 7.1 foundation",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(health.router)
app.include_router(tenants.router)
app.include_router(work_orders.router)
app.include_router(template_profiles.router)
app.include_router(workflows.router)
app.include_router(output_packages.router)
app.include_router(candidate_review.router)
app.include_router(audit_log.router)
app.include_router(adapter_credentials.router)
app.include_router(adapter_credentials.status_router)
app.include_router(llm.router)
app.include_router(llm.tool_catalog_router)
app.include_router(tools_routes.router)
# MegaLoop Theta — Tools Locker write-side + skill import + MCP test
app.include_router(tool_locker.tool_catalog_write_router)
app.include_router(tool_locker.skills_router)
app.include_router(channels.router)
app.include_router(aiden.router)
app.include_router(dispatch.router)
app.include_router(workspace.router)
app.include_router(canonical_facts_routes.router)
app.include_router(chat_sessions.router)
app.include_router(auth_routes.router)
app.include_router(webhooks.router)
