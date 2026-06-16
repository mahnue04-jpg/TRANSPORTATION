# PHASE 54 PREVIEW RECOVERY RUNBOOK

## Objective
Recover PHASE 54 preview runtime to a single stable port and verify launch integrity end-to-end.

## Recovery Signals
Use this runbook when any of the following occurs:
1. http://127.0.0.1:8010 refuses connections.
2. Preview UI opens but expected PHASE 54 runtime endpoints are missing.
3. Mixed 8010 and 8011 behavior appears across tabs and requests.
4. Dashboard refresh loops and aborted fetch diagnostics spike after restart.

## Recovery Procedure

### Step 1 - Start canonical runtime with hotfix safeguards
From repository root:
- powershell -ExecutionPolicy Bypass -File .\scripts\phase54_preview_up.ps1 -HostName 127.0.0.1 -Port 8010 -OpenBrowser -StopConflictingPreviewRuntimes

What this does:
1. Detects listeners on 8010/8011.
2. Stops conflicting uvicorn app.main preview runtimes on non-target port.
3. Starts canonical runtime via scripts/dev_up.ps1 on 8010.
4. Runs scripts/phase54_preview_validate.py.
5. If validation fails, forces restart and retries validation automatically.
6. Writes runtime status to .runtime/phase54_preview_hotfix_status.json.

### Step 2 - Validate runtime explicitly (manual replay)
- $env:AMICOR_HOST='127.0.0.1'; $env:AMICOR_PORT='8010'; & .\.venv\Scripts\python.exe .\scripts\phase54_preview_validate.py

Expected success criteria:
1. api_health/app/governance status 200.
2. OpenAPI includes:
   - /api/health-isf/operations/runtime-state
   - /api/health-isf/operations/runtime-replay
   - /api/health-isf/operations/preview-runtime-status
3. Route registration reports websocket route:
   - /api/health-isf/ws/live/{organization_id}/{user_id}
4. Alternate-port probe shows 8011 connection refused.
5. success=true.

### Step 3 - Open preview surfaces
- powershell -ExecutionPolicy Bypass -File .\scripts\phase54_frontend_preview.ps1 -HostName 127.0.0.1 -Port 8010

This opens:
- http://127.0.0.1:8010/app?voiceDiag=1&liveVerify=1
- http://127.0.0.1:8010/app/operations/governance?voiceDiag=1&liveVerify=1

## Verification Checklist
1. Port ownership:
   - 8010 listening with uvicorn app.main
   - 8011 not listening
2. Health endpoint:
   - http://127.0.0.1:8010/api/health returns 200
3. Validator success:
   - required runtime paths present
   - websocket route registered
4. Focused realtime regression passes:
   - backend/tests/test_health_isf_live_flow.py::TestRealtimeWebSocketFlow::test_authenticated_websocket_receives_live_ride_created_event

## Troubleshooting Notes
1. If browser still shows heavy 403/ERR_ABORTED noise, confirm tab URL host/port is 8010, not stale 8011.
2. A reachable app page is not enough. Always require route-level validation from scripts/phase54_preview_validate.py.
3. If startup appears healthy but route checks fail, rerun phase54_preview_up.ps1 and allow forced restart recovery to complete.

## Current Confirmed Recovery State
1. 8010 healthy and serving preview runtime.
2. 8011 closed and refusing connections.
3. PHASE 54 runtime-state, runtime-replay, and preview-runtime-status endpoints validated.
4. Websocket route registration and focused websocket test confirmed.
