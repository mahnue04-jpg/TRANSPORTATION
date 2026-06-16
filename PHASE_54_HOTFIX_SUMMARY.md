# PHASE 54 HOTFIX SUMMARY

## Scope
PHASE 54 HOTFIX - Preview Runtime Recovery and Stable Launch Verification.

This hotfix addresses localhost preview refusal, port split instability, stale runtime reuse, and launch reproducibility without changing PHASE 49-54 architecture.

## Root Cause
1. Runtime split across ports 8010 and 8011 allowed stale uvicorn processes to remain active.
2. A reachable preview URL did not guarantee the expected PHASE 54 route map was loaded.
3. Existing browser tab/session noise on 8011 (403 plus aborted fetch diagnostics) obscured true 8010 runtime state.

## Hotfix Changes Applied
1. Updated default PHASE 54 preview port to 8010 in startup and validation scripts.
2. Added conflicting-runtime detection and cleanup for uvicorn app.main listeners on 8010/8011.
3. Added startup status persistence file:
   - .runtime/phase54_preview_hotfix_status.json
4. Added recovery flow:
   - if first validation fails, force restart and re-validate automatically.
5. Hardened validator:
   - retry-aware health/app/governance checks,
   - OpenAPI required-path verification,
   - route-registration verification from app.main import,
   - alternate-port probe diagnostics.

## Verified Runtime State (Post-Hotfix)
Port and process verification:
- listen port=8010 pid=23204 cmd=python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level info
- health port=8010 status=200
- listen port=8011 none
- health port=8011 connection refused

Validation snapshot (scripts/phase54_preview_validate.py):
- success=true
- required paths present:
  - /api/health-isf/operations/preview-runtime-status
  - /api/health-isf/operations/runtime-replay
  - /api/health-isf/operations/runtime-state
- websocket route registered:
  - /api/health-isf/ws/live/{organization_id}/{user_id}
- alternate port probe confirms 8011 refusal (WinError 10061)

Focused websocket regression:
- backend/tests/test_health_isf_live_flow.py::TestRealtimeWebSocketFlow::test_authenticated_websocket_receives_live_ride_created_event
- result: 1 passed

Frontend preview helper validation:
- scripts/phase54_frontend_preview.ps1 opened 8010 preview and governance URLs successfully.

## Exact Launch Commands
From repository root:

1. Canonical PHASE 54 preview launch with recovery safeguards
PowerShell:
- powershell -ExecutionPolicy Bypass -File .\scripts\phase54_preview_up.ps1 -HostName 127.0.0.1 -Port 8010 -OpenBrowser -StopConflictingPreviewRuntimes

2. Open frontend preview surfaces only
PowerShell:
- powershell -ExecutionPolicy Bypass -File .\scripts\phase54_frontend_preview.ps1 -HostName 127.0.0.1 -Port 8010

3. Direct startup and route validation
PowerShell:
- $env:AMICOR_HOST='127.0.0.1'; $env:AMICOR_PORT='8010'; & .\.venv\Scripts\python.exe .\scripts\phase54_preview_validate.py

## Stable URLs
- http://127.0.0.1:8010/app?voiceDiag=1&liveVerify=1
- http://127.0.0.1:8010/app/operations/governance?voiceDiag=1&liveVerify=1
- http://127.0.0.1:8010/api/health

## Operational Note
Browser diagnostics captured on the legacy 8011 tab show 403 and ERR_ABORTED events tied to stale/auth context on that old port. These do not invalidate the recovered 8010 runtime, which now passes route-level and websocket-level PHASE 54 checks.

## Outcome
PHASE 54 preview runtime recovery is complete:
- localhost refusal scenario diagnosed and mitigated,
- startup flow repaired with automatic recovery,
- resilience safeguards in place,
- stable launch verification on 8010 confirmed.
