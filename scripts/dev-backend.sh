#!/usr/bin/env bash
# Start Camoufox Console Local API (mock launch by default)
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
export CAMOUFOX_REAL_LAUNCH="${CAMOUFOX_REAL_LAUNCH:-0}"
exec .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 50325
