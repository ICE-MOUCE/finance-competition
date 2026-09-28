#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PID_FILE="$ROOT/runtime/server.pid"
LOG_FILE="$ROOT/runtime/server.log"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "server already running pid=$old_pid"
    exit 0
  fi
fi

cd "$ROOT"
nohup "$ROOT/.venv/bin/python" -m uvicorn app.main:app \
  --host "${HKIPO_HOST:-127.0.0.1}" \
  --port "${HKIPO_PORT:-8000}" \
  >"$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"
sleep 2
if ! kill -0 "$pid" 2>/dev/null; then
  cat "$LOG_FILE"
  exit 1
fi
echo "server started pid=$pid log=$LOG_FILE"
