#!/usr/bin/env bash
# Clean-baseline reset for the IWO3 Postgres database.
#
# - Drops and recreates `aiden_iwo3`.
# - Applies Drizzle schema (IWO2-parity lane — Loop 1 narrow schema).
# - Applies Alembic migrations to head (IWO3-native lane; empty in Loop 1).
# - Populates `migration_source_manifest`.
#
# Preconditions:
#   - docker compose up -d aiden-iwo3-postgres  (from repo root)
#   - IWO3_DATABASE_URL set (see infra/local/.env.example)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${IWO3_DATABASE_URL:-}" ]]; then
  if [[ -f .env ]]; then
    set -a; source .env; set +a
  fi
fi
: "${IWO3_DATABASE_URL:?IWO3_DATABASE_URL is required}"

echo "[reset-iwo3] Checking Postgres reachability..."
docker exec aiden-iwo3-postgres pg_isready -U "${IWO3_PG_USER:-iwo3}" -d aiden_iwo3 >/dev/null

echo "[reset-iwo3] Dropping + recreating database 'aiden_iwo3'..."
docker exec aiden-iwo3-postgres psql -U "${IWO3_PG_USER:-iwo3}" -d postgres -c "DROP DATABASE IF EXISTS aiden_iwo3;"
docker exec aiden-iwo3-postgres psql -U "${IWO3_PG_USER:-iwo3}" -d postgres -c "CREATE DATABASE aiden_iwo3;"

echo "[reset-iwo3] Applying Drizzle schema (IWO2-parity lane)..."
npx drizzle-kit push --config drizzle.config.iwo3.ts

echo "[reset-iwo3] Applying Alembic migrations (IWO3-native lane)..."
(cd apps/api-fastapi && uv run alembic upgrade head)

echo "[reset-iwo3] Populating migration_source_manifest..."
npx tsx infra/local/manifest-populate.ts

echo "[reset-iwo3] Done."
