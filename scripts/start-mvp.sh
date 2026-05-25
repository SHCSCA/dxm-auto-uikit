#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/data"

cd "$ROOT/app/backend"
if [ -x "$ROOT/app/backend/.venv/Scripts/python.exe" ]; then
  PYTHON_EXE="$ROOT/app/backend/.venv/Scripts/python.exe"
elif [ -x "$ROOT/app/backend/.venv/bin/python" ]; then
  PYTHON_EXE="$ROOT/app/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python)"
else
  echo "Python 3.11+ is required. Create app/backend/.venv or add python to PATH." >&2
  exit 1
fi
nohup "$PYTHON_EXE" -m uvicorn src.main:app --host 127.0.0.1 --port 8000 > "$ROOT/data/backend.log" 2>&1 &

cd "$ROOT/app/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
nohup npm run dev > "$ROOT/data/frontend.log" 2>&1 &

echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://127.0.0.1:5173"
echo "Desktop shell can target DXM_FRONTEND_URL=http://127.0.0.1:5173"
