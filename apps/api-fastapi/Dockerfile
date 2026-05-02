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

# Loop Eta phase 1.3 (post-close hosting parity) — install uv + Node.
# Node is required so the FastAPI runtime can spawn the bundled Stitch
# MCP stdio proxy at vendor/stitch-mcp-proxy.mjs as a child process.
# Without Node in the image, the hosted Stitch surface returns
# command_resolved=false and the live Stitch dual-gate refuses dispatch.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

WORKDIR /app

# Copy only manifests first for Docker layer caching — deps re-resolve
# only when pyproject.toml or uv.lock change.
COPY apps/api-fastapi/pyproject.toml apps/api-fastapi/uv.lock ./apps/api-fastapi/
RUN cd apps/api-fastapi && uv sync --frozen --no-dev

# Vendor the Stitch MCP proxy + install its npm deps. See
# apps/api-fastapi/vendor/README.md for the rationale (avoid sidecars +
# IWO2-local-path assumptions on Railway).
COPY apps/api-fastapi/vendor/package.json ./apps/api-fastapi/vendor/
RUN cd apps/api-fastapi/vendor && npm install --omit=dev --no-audit --no-fund

# Copy the FastAPI app source (includes vendor/stitch-mcp-proxy.mjs).
COPY apps/api-fastapi/ ./apps/api-fastapi/

# Default Stitch MCP command points at the vendored proxy. Operators
# may override via Railway env if they want to swap to a sidecar.
ENV STITCH_MCP_COMMAND="node /app/apps/api-fastapi/vendor/stitch-mcp-proxy.mjs"

# Railway sets PORT; default 5500 matches local dev convention.
EXPOSE 5500
ENV PORT=5500

WORKDIR /app/apps/api-fastapi

# uvicorn binds 0.0.0.0 so the container is reachable inside Railway's
# ingress. PORT is supplied by Railway at runtime.
CMD ["sh", "-c", "/opt/iwo3-venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PORT:-5500}"]
