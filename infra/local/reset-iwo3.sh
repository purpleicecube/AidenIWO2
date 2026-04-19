#!/usr/bin/env bash
# Clean-baseline reset for the IWO3 Postgres database.
#
# Works in both local Docker dev and GitHub Actions CI because it never
# shells into a named container. It talks to Postgres via `pg` using
# IWO3_DATABASE_URL. Local dev + CI converge on the same reset path.
#
# Steps:
#   1. Wipe the `public` schema in `aiden_iwo3` (drops all tables and
#      enums in one statement — idempotent, independent of creator).
#   2. Apply all Drizzle-generated SQL in `db/migrations/*.sql`
#      (via infra/local/apply-migrations.ts — avoids the interactive
#      `drizzle-kit push` TUI).
#   3. Apply Alembic migrations to head for the IWO3-native lane
#      (empty in Loop 1; toolchain still runs if `uv` is available).
#   4. Populate `migration_source_manifest` from the explicit registry
#      (ADR-008 — unknown tables fail the test, not the populate).
#
# Preconditions:
#   - IWO3_DATABASE_URL set and reachable (see infra/local/.env.example)
#   - Node deps installed (`npm ci`) so tsx + pg are available
#   - Optional: uv installed with `uv sync --extra dev` in
#     apps/api-fastapi; skipped with a warning if not present.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${IWO3_DATABASE_URL:-}" ]]; then
  if [[ -f .env ]]; then
    set -a; source .env; set +a
  fi
fi
: "${IWO3_DATABASE_URL:?IWO3_DATABASE_URL is required}"

echo "[reset-iwo3] Wiping public schema in aiden_iwo3..."
node -e "
const { Client } = require('pg');
(async () => {
  const c = new Client({ connectionString: process.env.IWO3_DATABASE_URL });
  await c.connect();
  try {
    await c.query('DROP SCHEMA IF EXISTS public CASCADE');
    await c.query('CREATE SCHEMA public');
    await c.query('GRANT ALL ON SCHEMA public TO public');
  } finally { await c.end(); }
})().catch(e => { console.error(e); process.exit(1); });
"

echo "[reset-iwo3] Applying Drizzle migrations (IWO2-parity lane + Loop 1 foundation)..."
npx tsx infra/local/apply-migrations.ts

echo "[reset-iwo3] Applying Alembic migrations (IWO3-native lane)..."
if command -v uv >/dev/null 2>&1; then
  if [[ -d apps/api-fastapi/.venv ]] || (cd apps/api-fastapi && uv sync --extra dev >/dev/null 2>&1); then
    (cd apps/api-fastapi && uv run alembic upgrade head) || {
      echo "[reset-iwo3] WARN: alembic upgrade failed or had no migrations — continuing."
    }
  else
    echo "[reset-iwo3] WARN: uv sync failed; skipping alembic upgrade."
  fi
else
  echo "[reset-iwo3] WARN: uv not installed; skipping alembic upgrade."
fi

echo "[reset-iwo3] Populating migration_source_manifest..."
npx tsx infra/local/manifest-populate.ts

echo "[reset-iwo3] Done."
