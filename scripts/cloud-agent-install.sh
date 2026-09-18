#!/usr/bin/env bash
# Cloud Agent install: prepare the Amicor FastAPI backend (which also serves the
# static frontend) for local development. Idempotent: safe to run repeatedly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── System dependency: python venv support (Debian/Ubuntu ships it separately) ──
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  sudo apt-get update -qq
  sudo apt-get install -y "python${PYVER}-venv"
fi

# ── Python virtual environment ────────────────────────────────────────────────
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt

# ── Local .env with safe development defaults (never overwrite a real one) ──────
# Real secrets provided as Cloud Agent environment variables take precedence:
# load_dotenv() does not override values already present in the environment.
if [ ! -f .env ]; then
  SECRET_KEY_VALUE="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
  JWT_SECRET_VALUE="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
  cat > .env <<EOF
# Auto-generated for local development by scripts/cloud-agent-install.sh.
# Replace OPENAI_API_KEY with a real key (or set it as a Cloud Agent secret) to
# enable AI chat. All other values are safe local defaults.
OPENAI_API_KEY=sk-local-dev-placeholder-not-a-real-key
SECRET_KEY=${SECRET_KEY_VALUE}
JWT_SECRET=${JWT_SECRET_VALUE}
LOG_LEVEL=INFO
APP_VERSION=dev
DB_FILENAME=${REPO_ROOT}/backend/data/chat.db
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
PLATFORM_OPS_DOCUMENT_STORAGE=local_dev
PLATFORM_OPS_DOCUMENT_STORAGE_PATH=${REPO_ROOT}/backend/data/onboarding_docs
EOF
fi

# ── Writable data directory for the SQLite database + local document storage ────
mkdir -p backend/data backend/data/onboarding_docs

echo "Amicor Cloud Agent install complete."
