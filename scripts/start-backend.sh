#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../app/backend"
exec /root/.hermes/hermes-agent/venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
