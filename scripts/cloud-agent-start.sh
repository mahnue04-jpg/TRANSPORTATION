#!/usr/bin/env bash
# Cloud Agent start: launch the Amicor FastAPI app (API + static frontend) on
# port 8000. Loads local development defaults from .env; real environment
# variables provided by the Cloud Agent take precedence.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

mkdir -p backend/data backend/data/onboarding_docs

cd backend
exec ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
