#!/usr/bin/env bash
# dev-start.sh — Canonical IWO2 dev startup (Loop 31)
# Checks Docker deps, kills stale processes, starts server with health confirmation.
set -euo pipefail

PORT=5001
PG_CONTAINER="aiden-postgres"
PG_PORT=5433
HEALTH_TIMEOUT=15

echo "[dev-start] IWO2 development server startup"
echo "==========================================="

# ── Step 1: Check Docker / PostgreSQL ─────────────────────────────────────────
echo ""
echo "[1/4] Checking PostgreSQL ($PG_CONTAINER on port $PG_PORT)..."

if ! command -v docker &>/dev/null; then
  echo "  ERROR: docker not found. Install Docker first."
  exit 1
fi

PG_STATUS=$(docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null || echo "missing")

if [ "$PG_STATUS" = "missing" ]; then
  echo "  ERROR: Container '$PG_CONTAINER' not found."
  echo "  Create it with: docker run -d --name $PG_CONTAINER -p $PG_PORT:5432 -e POSTGRES_DB=aiden_iwo -e POSTGRES_PASSWORD=... postgres:16"
  exit 1
elif [ "$PG_STATUS" = "false" ]; then
  echo "  Container stopped — starting..."
  docker start "$PG_CONTAINER" >/dev/null
  sleep 2
  PG_STATUS=$(docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null)
  if [ "$PG_STATUS" != "true" ]; then
    echo "  ERROR: Failed to start $PG_CONTAINER"
    exit 1
  fi
  echo "  Started."
else
  echo "  Running."
fi

# ── Step 2: Kill stale processes ──────────────────────────────────────────────
echo ""
echo "[2/4] Checking port $PORT..."

STALE_PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$STALE_PIDS" ]; then
  echo "  Killing stale process(es) on port $PORT: $STALE_PIDS"
  echo "$STALE_PIDS" | xargs kill -9 2>/dev/null || true
  sleep 1
else
  echo "  Port $PORT is free."
fi

# ── Step 3: Start server ─────────────────────────────────────────────────────
echo ""
echo "[3/4] Starting server..."

cd "$(dirname "$0")"
nohup npx tsx --env-file=.env server/index.ts > /tmp/iwo2-server.log 2>&1 &
SERVER_PID=$!
echo "  PID: $SERVER_PID"
echo "  Log: /tmp/iwo2-server.log"

# ── Step 4: Health check ─────────────────────────────────────────────────────
echo ""
echo "[4/4] Waiting for health check (${HEALTH_TIMEOUT}s timeout)..."

for i in $(seq 1 $HEALTH_TIMEOUT); do
  if curl -sf http://localhost:$PORT/api/health >/dev/null 2>&1; then
    VERSION=$(curl -sf http://localhost:$PORT/api/health | python3 -c "import json,sys; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
    echo ""
    echo "==========================================="
    echo "[dev-start] IWO2 v${VERSION} running on http://localhost:$PORT"
    echo "  PostgreSQL: $PG_CONTAINER (port $PG_PORT)"
    echo "  Server PID: $SERVER_PID"
    echo "  Log: /tmp/iwo2-server.log"
    echo "  Dev login: curl -c /tmp/aiden-cookie.txt http://localhost:$PORT/api/login"
    echo "==========================================="
    exit 0
  fi
  sleep 1
done

echo "  ERROR: Server did not respond within ${HEALTH_TIMEOUT}s"
echo "  Check /tmp/iwo2-server.log for errors:"
tail -10 /tmp/iwo2-server.log
exit 1
