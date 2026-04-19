#!/usr/bin/env bash
# Single-entrypoint Loop 1 baseline check. Runs every verification step
# the acceptance criteria in IWO3_LOOP_1_PLAN §6 require. Invoked locally
# and from .github/workflows/ci.yml.
#
# Preconditions (local):
#   - docker compose -f infra/local/docker-compose.iwo3-postgres.yml up -d
#   - .env populated (see infra/local/.env.example)
#
# Preconditions (CI):
#   - Postgres service container provides IWO3_DATABASE_URL.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "[baseline] node --version:  $(node --version)"
echo "[baseline] python --version: $(python --version 2>&1 || python3 --version)"

echo "[baseline] npm run check"
npm run check

echo "[baseline] npm run test"
npm run test

echo "[baseline] pytest apps/api-fastapi/tests"
(cd apps/api-fastapi && uv run pytest)

echo "[baseline] reset-iwo3.sh"
bash infra/local/reset-iwo3.sh

echo "[baseline] seed-iwo3.sh"
bash infra/local/seed-iwo3.sh

echo "[baseline] gitleaks"
gitleaks detect --no-banner --exit-code 1 --config .gitleaks.toml

echo "[baseline] All checks green."
