#!/usr/bin/env bash
# health_check.sh — External production health check script.
#
# Usage:
#   ./scripts/health_check.sh [HOST] [PORT]
#
# Defaults: HOST=localhost, PORT=8000
# Exit 0 = healthy, Exit 1 = unhealthy.
#
# Designed to be called by monitoring systems, CI pipelines,
# or load-balancer health probes that can't use Docker HEALTHCHECK.

set -euo pipefail

HOST="${1:-localhost}"
PORT="${2:-8000}"
BASE="http://${HOST}:${PORT}"

PASS="[PASS]"
FAIL="[FAIL]"
WARN="[WARN]"

echo "═══════════════════════════════════════════════════════"
echo "  Amicor health check  →  ${BASE}"
echo "═══════════════════════════════════════════════════════"

fail_count=0

run_check() {
  local label="$1"
  local url="$2"
  local expected_status="${3:-200}"

  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${url}" 2>/dev/null || echo "000")

  if [ "${status}" = "${expected_status}" ]; then
    echo "  ${PASS}  ${label}  (HTTP ${status})"
  else
    echo "  ${FAIL}  ${label}  (expected ${expected_status}, got ${status})"
    fail_count=$((fail_count + 1))
  fi
}

# ── Liveness ─────────────────────────────────────────────────────────────────
run_check "Liveness  /api/health"        "${BASE}/api/health"        200

# ── Readiness (deep) ─────────────────────────────────────────────────────────
run_check "Readiness /api/health/detail" "${BASE}/api/health/detail" 200

# ── Static assets ────────────────────────────────────────────────────────────
run_check "Static    /static/index.html" "${BASE}/static/index.html" 200

echo "═══════════════════════════════════════════════════════"
if [ "${fail_count}" -eq 0 ]; then
  echo "  ✓  All checks passed."
  exit 0
else
  echo "  ✗  ${fail_count} check(s) failed."
  exit 1
fi
