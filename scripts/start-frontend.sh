#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/app/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
exec npm run dev
