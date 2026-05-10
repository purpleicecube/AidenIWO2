#!/usr/bin/env bash
# Loop Xi-followup (Test DB Split Darkmode 2026-05-10) —
# canonical fresh-DB integration-test wrapper.
#
# Splits IWO3 local Postgres usage into two explicit lanes:
#
#   IWO3_DATABASE_URL       -> local-live  (operator app/dev DB; allowed to drift)
#   IWO3_TEST_DATABASE_URL  -> local-test-fresh  (disposable; reset+reseed each run)
#
# This script wraps the existing reset-iwo3.sh + seed-iwo3.sh + vitest +
# pytest entrypoints inside a subshell where IWO3_DATABASE_URL is
# temporarily pinned to IWO3_TEST_DATABASE_URL. The operator's parent
# shell + their live local DB are NEVER mutated.
#
# Defenses against accidentally repointing the live DB:
#   1. Refuses if IWO3_TEST_DATABASE_URL is unset.
#   2. Refuses if IWO3_TEST_DATABASE_URL == IWO3_DATABASE_URL.
#   3. Refuses if the test URL's database name does not end with `_test`.
#   4. Prints both URLs before doing anything destructive so the operator
#      can sanity-check.
#
# Idempotent: creates the test database via the postgres admin DB if
# it does not already exist.
#
# Usage:
#   bash infra/local/test-integration-iwo3.sh
#
# Or via npm:
#   npm run test:integration

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Allow .env to populate the test URL when not already in env.
if [[ -z "${IWO3_TEST_DATABASE_URL:-}" ]] && [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${IWO3_TEST_DATABASE_URL:?IWO3_TEST_DATABASE_URL is required (see infra/local/.env.example)}"

LIVE_URL="${IWO3_DATABASE_URL:-}"
TEST_URL="$IWO3_TEST_DATABASE_URL"

# Defense (2): live and test must differ.
if [[ -n "$LIVE_URL" && "$TEST_URL" == "$LIVE_URL" ]]; then
  echo "[test-integration] REFUSE: IWO3_TEST_DATABASE_URL must differ from IWO3_DATABASE_URL"
  echo "  live: $LIVE_URL"
  echo "  test: $TEST_URL"
  exit 1
fi

# Defense (3): test DB name must end with _test.
TEST_DB_NAME="$(printf '%s' "$TEST_URL" | sed -E 's|.*/([^/?]+).*|\1|')"
if [[ ! "$TEST_DB_NAME" =~ _test$ ]]; then
  echo "[test-integration] REFUSE: test DB name must end with '_test' (got: $TEST_DB_NAME)"
  echo "  This guard prevents accidentally pointing the wrapper at a"
  echo "  non-test DB (e.g. 'aiden_iwo3') and wiping it via reset-iwo3.sh."
  exit 1
fi

# Defense (4): print both URLs so the operator sees what's about to happen.
echo "[test-integration] LIVE DB:  ${LIVE_URL:-(unset)}"
echo "[test-integration] TEST DB:  $TEST_URL"
echo "[test-integration] target:   $TEST_DB_NAME (will be reset + reseeded)"

# Bootstrap: CREATE DATABASE if it doesn't exist. We derive an admin
# URL pointing at the `postgres` administrative database on the same
# host:port so we can `CREATE DATABASE` without already being inside
# the target DB. URL parsing happens in node where it's robust to
# query strings and edge characters in the password.

echo "[test-integration] 1/6  ensuring test DB exists"
node -e "
const { Client } = require('pg');
(async () => {
  const testUrl = process.env.IWO3_TEST_DATABASE_URL;
  const u = new URL(testUrl);
  const dbName = decodeURIComponent(u.pathname.replace(/^\//, ''));
  if (!/_test\$/.test(dbName)) {
    console.error('REFUSE: derived test DB name does not end with _test:', dbName);
    process.exit(1);
  }
  const adminUrl = new URL(testUrl);
  adminUrl.pathname = '/postgres';
  const c = new Client(adminUrl.toString());
  await c.connect();
  const r = await c.query('SELECT 1 FROM pg_database WHERE datname = \$1', [dbName]);
  if (r.rowCount === 0) {
    // pg has no parameter binding for DDL; safe because we just
    // verified dbName ends with _test and the regex blocks
    // injection-bearing characters via the suffix lock.
    await c.query('CREATE DATABASE \"' + dbName.replace(/\"/g, '\"\"') + '\"');
    console.log('  created database', dbName);
  } else {
    console.log('  database', dbName, 'already exists');
  }
  await c.end();
})().catch((err) => { console.error(err); process.exit(1); });
"

# Pin IWO3_DATABASE_URL to the test URL for the rest of this subshell.
# The operator's parent-shell env stays unchanged.
export IWO3_DATABASE_URL="$TEST_URL"
echo "[test-integration] (subshell) IWO3_DATABASE_URL pinned to test URL"

# Match CI's environment so adapter integration tests behave the same
# locally as on CI. CI's .github/workflows/ci.yml only sets
# IWO3_DATABASE_URL + IWO3_PG_* + NODE_ENV=test; live-adapter flags
# are deliberately unset so integration tests exercise the test-double
# code paths. The operator's .env may set GAMMA_LIVE_ENABLED=true for
# real operator testing — we unset it here so it doesn't leak into
# the integration suite.
export NODE_ENV=test
unset GAMMA_LIVE_ENABLED
echo "[test-integration] (subshell) NODE_ENV=test, GAMMA_LIVE_ENABLED unset"

echo "[test-integration] 2/6  reset (wipe public schema + apply migrations)"
bash infra/local/reset-iwo3.sh

echo "[test-integration] 3/6  seed (Loop 1+ durable rows)"
bash infra/local/seed-iwo3.sh

echo "[test-integration] 4/6  npm run check (typecheck)"
npm run check

echo "[test-integration] 5/6  vitest (Node integration suite)"
npm run test

echo "[test-integration] 6/6  pytest (api-fastapi + console-streamlit)"
if command -v uv >/dev/null 2>&1; then
  (cd apps/api-fastapi && IWO3_DATABASE_URL="$TEST_URL" uv run pytest)

  if [[ -d apps/console-streamlit/tests ]]; then
    # The console-streamlit api_client tests spawn a FastAPI subprocess
    # on a fixed port (8765 by default). If the previous step's pytest
    # left a lingering uvicorn behind (rare; usually only happens after
    # a debug-mode kill), the new fixture's bind would race and time
    # out. Reap any matching `python -m uvicorn main:app` process owned
    # by this user before the next pytest spins up its own subprocess.
    pkill -u "$USER" -f 'python -m uvicorn main:app' 2>/dev/null || true
    sleep 1

    (cd apps/api-fastapi && IWO3_DATABASE_URL="$TEST_URL" uv run pytest ../console-streamlit/tests -v)
  fi
else
  echo "[test-integration] WARN: uv not installed — skipping pytest"
fi

echo "[test-integration] done — fresh-DB integration run complete on '$TEST_DB_NAME'"
echo "[test-integration] live DB '${LIVE_URL:-(unset)}' was not touched"
