#!/usr/bin/env bash
# Single-entrypoint Loop 1 baseline check. Runs every verification step
# the Loop 1 acceptance criteria require. Invoked locally and from
# .github/workflows/ci.yml.
#
# Order (per CODEX Loop 1 Phase 1 review — must match, with Loop 4
# Phase 4 adding step 5 `iwo3-lint` before pytest):
#   1. npm run check          (typecheck)
#   2. reset-iwo3.sh          (DB to known state)
#   3. seed-iwo3.sh           (Loop 1 durable rows)
#   4. npm run test           (Vitest — IWO2 + new IWO3 integration tests
#                              + Loop 4 Phase 4 lint rule unit + clean)
#   5. uv run pytest          (api-fastapi smoke)
#   6. gitleaks               (secret scan — soft-skipped when CLI absent
#                              and run separately as gitleaks-action in CI)
# The `iwo3-lint` rule unit tests + full-repo-clean assertion run inside
# `npm run test` via the Vitest include pattern `tests/tools/**/*.test.ts`.
#
# Preconditions (local):
#   - Postgres running (see docker-compose.iwo3-postgres.yml or
#     docs/runbooks/startup.md fallback for hosts where compose is broken)
#   - .env populated (see infra/local/.env.example)
#   - Node deps installed (`npm ci`)
#   - Python deps optional but recommended (`cd apps/api-fastapi && uv sync --extra dev`)
#
# Preconditions (CI):
#   - Postgres service container provides IWO3_DATABASE_URL
#   - setup-node + setup-python + setup-uv + npm ci + uv sync --extra dev

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "[baseline] node:    $(node --version)"
echo "[baseline] python:  $(python3 --version 2>&1 || echo 'not present')"

echo "[baseline] 1/6  npm run check"
npm run check

echo "[baseline] 2/6  reset-iwo3.sh"
bash infra/local/reset-iwo3.sh

echo "[baseline] 3/6  seed-iwo3.sh"
bash infra/local/seed-iwo3.sh

echo "[baseline] 4/6  npm run test"
npm run test

echo "[baseline] 5/6  pytest apps/api-fastapi/tests"
if command -v uv >/dev/null 2>&1; then
  (cd apps/api-fastapi && uv run pytest)
else
  echo "[baseline] WARN: uv not installed — skipping pytest."
fi

echo "[baseline] 6/6  gitleaks"
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --no-banner --exit-code 1 --config .gitleaks.toml
else
  echo "[baseline] WARN: gitleaks CLI not installed locally."
  echo "           CI runs gitleaks via gitleaks/gitleaks-action@v2 as a separate step."
  echo "           For local verification: brew install gitleaks or download from"
  echo "           https://github.com/gitleaks/gitleaks/releases and re-run."
fi

echo "[baseline] All checks green."
