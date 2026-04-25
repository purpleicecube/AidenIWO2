#!/usr/bin/env bash
# Alpha closeout γ.6 — single combined entry point.
#
# Use:
#   bash scripts/iwo3.sh up        # FastAPI + Streamlit (background)
#   bash scripts/iwo3.sh down      # stop both processes
#   bash scripts/iwo3.sh status    # show port + PID summary
#   bash scripts/iwo3.sh restart   # down + up
#
# Wraps run-iwo3-api.sh + run-iwo3-console.sh so operators don't need
# to remember two commands during an Alpha walkthrough.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cmd_up() {
  bash "$REPO_ROOT/scripts/run-iwo3-api.sh" --background
  bash "$REPO_ROOT/scripts/run-iwo3-console.sh" --background
  echo
  cmd_status
}

cmd_down() {
  for proc in "uvicorn main:app" "streamlit run Home.py"; do
    pids=$(pgrep -f "$proc" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
      echo "[iwo3] stopping: $proc ($pids)"
      echo "$pids" | xargs -r kill 2>/dev/null || true
    fi
  done
  sleep 2
}

cmd_status() {
  echo "[iwo3] status:"
  for entry in "8000:fastapi" "8501:streamlit" "5434:postgres"; do
    port="${entry%%:*}"; name="${entry##*:}"
    if ss -tln 2>/dev/null | grep -q ":$port "; then
      echo "  $name  on :$port  ✅"
    else
      echo "  $name  on :$port  —"
    fi
  done
  pid_api=$(pgrep -f "uvicorn main:app" 2>/dev/null | head -1 || true)
  pid_st=$(pgrep -f "streamlit run Home.py" 2>/dev/null | head -1 || true)
  if [[ -n "$pid_api" ]]; then echo "  api pid     $pid_api"; fi
  if [[ -n "$pid_st" ]]; then echo "  console pid $pid_st"; fi
  return 0
}

cmd_restart() {
  cmd_down
  cmd_up
}

case "${1:-status}" in
  up)      cmd_up ;;
  down)    cmd_down ;;
  status)  cmd_status ;;
  restart) cmd_restart ;;
  *)
    echo "usage: $0 {up|down|status|restart}"
    exit 2
    ;;
esac
