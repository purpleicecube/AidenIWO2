"""Loop 1 bootstrap + Loop 7 Phase 7.1 hardening — health + readiness."""

from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from deps import get_db_connection

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok", service="iwo3-api-fastapi", version="0.0.1"
    )


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(
        status="ok", service="iwo3-api-fastapi", version="0.0.1"
    )


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> ReadyResponse:
    row = await conn.fetchrow("SELECT 1 AS ok")
    return ReadyResponse(
        status="ok" if row and row["ok"] == 1 else "error",
        database="connected" if row and row["ok"] == 1 else "unreachable",
    )
