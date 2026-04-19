"""AIDEN IWO3 FastAPI runtime API — bootstrap.

Loop 1 scope: health endpoint only.
Future loops add auth, RBAC dependency, channel webhooks, workflow routes,
output adapter routes, render routes.
"""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="AIDEN IWO3 API",
    version="0.0.1",
    description="IWO3 runtime API and channel gateway (Loop 1 bootstrap)",
)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="iwo3-api-fastapi", version="0.0.1")
