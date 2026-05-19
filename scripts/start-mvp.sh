#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/app/backend"
nohup /root/.hermes/hermes-agent/venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 > "$ROOT/data/backend.log" 2>&1 &
cd "$ROOT/app/frontend"
nohup npm run dev > "$ROOT/data/frontend.log" 2>&1 &
echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://127.0.0.1:5173"
echo "Desktop shell can target DXM_FRONTEND_URL=http://127.0.0.1:5173"
