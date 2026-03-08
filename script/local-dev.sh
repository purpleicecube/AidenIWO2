#!/usr/bin/env bash
# local-dev.sh — Start AIDEN IWO for local development
# Usage: ./script/local-dev.sh [start|stop|status|reset]
set -euo pipefail
cd "$(dirname "$0")/.."

# Ensure correct Node.js version via nvm
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
if [ -f .nvmrc ]; then
  REQUIRED_NODE=$(cat .nvmrc | tr -d '[:space:]')
  CURRENT_NODE="v$(node --version 2>/dev/null | tr -d 'v')"
  if [ "v${CURRENT_NODE}" != "v${REQUIRED_NODE}" ]; then
    echo "[env] Switching Node.js to ${REQUIRED_NODE}..."
    nvm use "$REQUIRED_NODE" || nvm install "$REQUIRED_NODE"
  fi
  echo "[env] Node.js $(node --version) | npm $(npm --version)"
fi

CONTAINER="aiden-postgres"
PORT=5433
DB_USER="aiden"
DB_PASS="aiden_local"
DB_NAME="aiden_iwo"

start_db() {
  if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "[db] ${CONTAINER} already running"
  elif docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "[db] Starting stopped ${CONTAINER}..."
    docker start "$CONTAINER"
  else
    echo "[db] Creating ${CONTAINER} (port ${PORT}, volume aiden_pgdata)..."
    docker run -d \
      --name "$CONTAINER" \
      --restart unless-stopped \
      -e POSTGRES_USER="$DB_USER" \
      -e POSTGRES_PASSWORD="$DB_PASS" \
      -e POSTGRES_DB="$DB_NAME" \
      -p "${PORT}:5432" \
      -v aiden_pgdata:/var/lib/postgresql/data \
      postgres:16-alpine
  fi

  echo "[db] Waiting for PostgreSQL..."
  for i in $(seq 1 15); do
    if docker exec "$CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
      echo "[db] Ready"
      return 0
    fi
    sleep 1
  done
  echo "[db] ERROR: PostgreSQL did not become ready in 15s"
  return 1
}

push_schema() {
  echo "[schema] Pushing Drizzle schema..."
  npm run db:push
}

start_app() {
  echo "[app] Starting dev server on http://localhost:5001"
  echo "[app] Login: open http://localhost:5001/api/login in your browser"
  npm run dev
}

stop_all() {
  echo "[app] Stopping dev server..."
  pkill -f "tsx.*server/index.ts" 2>/dev/null || true
  echo "[db] Stopping ${CONTAINER}..."
  docker stop "$CONTAINER" 2>/dev/null || true
  echo "Stopped."
}

show_status() {
  echo "=== Docker ==="
  docker ps --filter "name=${CONTAINER}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  echo ""
  echo "=== App ==="
  if pgrep -f "tsx.*server/index.ts" >/dev/null 2>&1; then
    echo "Dev server: RUNNING (port 5001)"
  else
    echo "Dev server: NOT running"
  fi
}

reset_db() {
  echo "[reset] This will DELETE all data. Ctrl+C to cancel..."
  sleep 3
  docker stop "$CONTAINER" 2>/dev/null || true
  docker rm "$CONTAINER" 2>/dev/null || true
  docker volume rm aiden_pgdata 2>/dev/null || true
  echo "[reset] Container and volume removed. Run './script/local-dev.sh start' to recreate."
}

case "${1:-start}" in
  start)
    start_db
    push_schema
    start_app
    ;;
  stop)
    stop_all
    ;;
  status)
    show_status
    ;;
  reset)
    reset_db
    ;;
  *)
    echo "Usage: $0 [start|stop|status|reset]"
    exit 1
    ;;
esac
