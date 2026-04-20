"""AIDEN IWO3 FastAPI runtime API.

Loop 7 Phase 7.1 expansion — routers + CORS + startup/shutdown hooks.
Previously Loop 1 bootstrap (health endpoint only).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from deps import shutdown_db_pool, startup_db_pool
from routes import health, tenants


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_db_pool()
    try:
        yield
    finally:
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
