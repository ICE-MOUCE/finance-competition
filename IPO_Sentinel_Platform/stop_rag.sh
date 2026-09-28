#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/ipo_rag_eval_final" && pwd)
PID_FILE=$ROOT/runtime/rag_api.pid
if [ ! -f $PID_FILE ]; then
  echo "RAG API is not running"
  exit 0
fi
pid=$(cat $PID_FILE)
if kill -0 $pid 2>/dev/null; then
  kill $pid
  for _ in $(seq 1 20); do
    kill -0 $pid 2>/dev/null || break
    sleep 0.25
  done
fi
rm -f $PID_FILE
echo "RAG API stopped"
