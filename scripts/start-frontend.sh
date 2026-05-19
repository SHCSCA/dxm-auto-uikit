#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../app/frontend"
exec npm run dev
