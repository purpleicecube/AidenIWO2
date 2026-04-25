#!/usr/bin/env bash
# Alpha closeout γ.6 — durable IWO3 Streamlit runner.
#
# Companion to run-iwo3-api.sh. Use:
#   bash scripts/run-iwo3-console.sh                # foreground
#   bash scripts/run-iwo3-console.sh --background   # nohup → /tmp/iwo3-console.log

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/apps/console-streamlit"
LOG="/tmp/iwo3-console.log"

export IWO3_API_BASE_URL="${IWO3_API_BASE_URL:-http://localhost:8000}"

# Stop anything bound to :8501.
existing=$(pgrep -f "streamlit run Home.py" || true)
if [[ -n "$existing" ]]; then
  echo "[run-iwo3-console] killing existing streamlit pids: $existing"
  echo "$existing" | xargs -r kill
  sleep 2
fi

cd "$APP_DIR"

if [[ "${1:-}" == "--background" ]]; then
  echo "[run-iwo3-console] starting background → $LOG"
  nohup .venv/bin/streamlit run Home.py \
    --server.port 8501 --server.headless true \
    > "$LOG" 2>&1 &
  disown
  sleep 4
  if ss -tln | grep -q ":8501 "; then
    echo "[run-iwo3-console] up on http://localhost:8501"
    exit 0
  fi
  echo "[run-iwo3-console] FAILED to bind :8501 — see $LOG"
  tail -30 "$LOG"
  exit 1
fi

exec .venv/bin/streamlit run Home.py --server.port 8501 --server.headless true
