#!/usr/bin/env bash
# Pre-Beta β.7+ — durable IWO3 FastAPI runner.
#
# CODEX flagged that ad-hoc background restarts during live testing
# left the runtime in unstable shape. This script is the boring,
# repeatable way to bring the IWO3 API up against the local DB.
#
# Use:
#   bash scripts/run-iwo3-api.sh                # foreground
#   bash scripts/run-iwo3-api.sh --background   # nohup → /tmp/iwo3-api.log
#
# Pre-conditions:
#   - aiden-iwo3-postgres container is up (port 5434)
#   - apps/api-fastapi/.venv exists (uv sync run once)
#   - one of:
#       a /home/virgina/VS_AIDEN_IWO3/.env (carries GROQ + OPENROUTER), or
#       b /home/virgina/VS_AIDEN_IWO2/.env (legacy fallback for live keys)
#
# Side-effects: kills any prior `uvicorn main:app` process bound to 8000.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/apps/api-fastapi"
LOG="/tmp/iwo3-api.log"

# ── env load. Layered:
#   1. IWO2 .env (carries the live LLM provider keys — single source of truth
#      for now; the keys are in two repos otherwise).
#   2. IWO3 .env (overrides DB url + worker flags + anything IWO3-specific).
# Either file is optional; this is dev posture, not production.
for env_file in "/home/virgina/VS_AIDEN_IWO2/.env" "$REPO_ROOT/.env"; do
  if [[ -f "$env_file" ]]; then
    echo "[run-iwo3-api] sourcing $env_file"
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
done

# Defaults that are safe for dev and overridable via the sourced env.
export IWO3_DATABASE_URL="${IWO3_DATABASE_URL:-postgresql://iwo3:iwo3@localhost:5434/aiden_iwo3}"
export IWO3_TELEGRAM_WORKER_DISABLED="${IWO3_TELEGRAM_WORKER_DISABLED:-true}"

# Sanity-check the keys without echoing the value.
for key in GROQ_API_KEY OPENROUTER_API_KEY; do
  val="${!key:-}"
  if [[ -z "$val" ]]; then
    echo "[run-iwo3-api] WARN: $key not set — Aiden chat will return credential_missing for non-shortcut prompts."
  else
    echo "[run-iwo3-api] $key present (len=${#val})"
  fi
done

# Stop anything bound to :8000.
existing=$(pgrep -f "uvicorn main:app" || true)
if [[ -n "$existing" ]]; then
  echo "[run-iwo3-api] killing existing uvicorn pids: $existing"
  echo "$existing" | xargs -r kill
  sleep 2
fi

cd "$APP_DIR"

if [[ "${1:-}" == "--background" ]]; then
  echo "[run-iwo3-api] starting background → $LOG"
  nohup .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 \
    > "$LOG" 2>&1 &
  disown
  sleep 4
  if ss -tln | grep -q ":8000 "; then
    echo "[run-iwo3-api] up on http://localhost:8000"
    exit 0
  fi
  echo "[run-iwo3-api] FAILED to bind :8000 — see $LOG"
  tail -30 "$LOG"
  exit 1
fi

exec .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
