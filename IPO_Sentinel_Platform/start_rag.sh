#!/usr/bin/env bash
set -euo pipefail

export TORCH_DEVICE_BACKEND_AUTOLOAD=0
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
unset PYTHONPATH PYTHONHOME CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT
export PATH=/usr/bin:/bin



ROOT=$(cd "$(dirname "$0")/ipo_rag_eval_final" && pwd)
PID_FILE=$ROOT/runtime/rag_api.pid
LOG_FILE=$ROOT/runtime/rag_api.log
mkdir -p $ROOT/runtime

if [ -f $PID_FILE ] && kill -0 $(cat $PID_FILE) 2>/dev/null; then
  echo "RAG API already running pid=$(cat $PID_FILE)"
  exit 0
fi

cd $ROOT
nohup env -i HOME=/home/ma-user PATH=/usr/bin:/bin TORCH_DEVICE_BACKEND_AUTOLOAD=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /usr/local/python3.11.15/bin/python3.11 "$ROOT/../run_rag_cpu.py" --host 127.0.0.1 --port 8000 >$LOG_FILE 2>&1 &
pid=$!
echo $pid > $PID_FILE
sleep 2
if ! kill -0 $pid 2>/dev/null; then
  cat $LOG_FILE
  exit 1
fi
echo "RAG API started pid=$pid log=$LOG_FILE"
