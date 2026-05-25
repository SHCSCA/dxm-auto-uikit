#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT/app/backend"

cd "$BACKEND_DIR"

if [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]; then
  PYTHON_EXE="$BACKEND_DIR/.venv/Scripts/python.exe"
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  PYTHON_EXE="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python)"
else
  echo "Python 3.11+ is required. Create app/backend/.venv or add python to PATH." >&2
  exit 1
fi

exec "$PYTHON_EXE" -m uvicorn src.main:app --host 127.0.0.1 --port 8000
