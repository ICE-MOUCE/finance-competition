#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="/home/ma-user/miniconda/envs/torch-2.9/bin/python"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  "$PYTHON" -m venv --system-site-packages "$ROOT/.venv"
fi

"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check -r "$ROOT/requirements.txt"
mkdir -p "$ROOT/runtime/reports" "$ROOT/runtime/models"
"$ROOT/.venv/bin/python" -c "import fastapi, fitz, pydantic, sklearn, uvicorn; print('dependencies ok')"

