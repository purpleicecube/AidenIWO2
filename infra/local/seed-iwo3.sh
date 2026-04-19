#!/usr/bin/env bash
# Seed IWO3 with the Loop 1 durable records.
#
# Loads:
#   db/seeds/clients.json            (2 rows)
#   db/seeds/users.json              (12 rows)
#   db/seeds/client_memberships.json (12 rows)
#   db/seeds/template_profiles.json  (5 rows)
#
# Idempotent: uses INSERT ... ON CONFLICT DO UPDATE.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${IWO3_DATABASE_URL:-}" ]]; then
  if [[ -f .env ]]; then
    set -a; source .env; set +a
  fi
fi
: "${IWO3_DATABASE_URL:?IWO3_DATABASE_URL is required}"

echo "[seed-iwo3] Seeding clients, users, client_memberships, template_profiles..."
npx tsx infra/local/seed-loader.ts

echo "[seed-iwo3] Seed receipt written to infra/local/last-seed.json"
