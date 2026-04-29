# IWO3 FastAPI runtime container — MegaLoop Hosting Foundation ζ.1
#
# Build context: REPO ROOT (not apps/api-fastapi/), so that future
# migration tooling can be optionally co-located. Build with:
#   docker build -f apps/api-fastapi/Dockerfile -t iwo3-api .
# or via Railway: set "Dockerfile Path" = "apps/api-fastapi/Dockerfile",
# "Root Directory" = "" (repo root).
#
# Migrations are NOT run at startup. Run them once per deploy via
#   railway run --service iwo3-api npx tsx infra/local/apply-migrations.ts
#   railway run --service iwo3-api npm run seed:iwo3
# from the operator's machine. Keeps the runtime image lean and
# makes migration timing explicit.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/iwo3-venv

# Install uv (matches the local toolchain pinned in ADR-007).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

WORKDIR /app

# Copy only manifests first for Docker layer caching — deps re-resolve
# only when pyproject.toml or uv.lock change.
COPY apps/api-fastapi/pyproject.toml apps/api-fastapi/uv.lock ./apps/api-fastapi/
RUN cd apps/api-fastapi && uv sync --frozen --no-dev

# Copy the FastAPI app source.
COPY apps/api-fastapi/ ./apps/api-fastapi/

# Railway sets PORT; default 5500 matches local dev convention.
EXPOSE 5500
ENV PORT=5500

WORKDIR /app/apps/api-fastapi

# uvicorn binds 0.0.0.0 so the container is reachable inside Railway's
# ingress. PORT is supplied by Railway at runtime.
CMD ["sh", "-c", "/opt/iwo3-venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PORT:-5500}"]
