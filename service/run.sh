#!/usr/bin/env bash
# Run the BT inference service locally.
# Usage: ./service/run.sh [port]
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${1:-8000}"
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

exec "$PY" -m uvicorn service.app.main:app --host 0.0.0.0 --port "$PORT" --reload
