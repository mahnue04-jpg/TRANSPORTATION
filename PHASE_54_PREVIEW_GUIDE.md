# PHASE 54 Preview Guide

## Purpose
Reliable local startup and visibility verification for Health ISF transportation runtime.

## Canonical Startup
```powershell
Set-Location "c:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild"
powershell -ExecutionPolicy Bypass -File ".\scripts\phase54_preview_up.ps1" -HostName "127.0.0.1" -Port 8011
```

## Frontend Surface Only
```powershell
Set-Location "c:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild"
powershell -ExecutionPolicy Bypass -File ".\scripts\phase54_frontend_preview.ps1" -HostName "127.0.0.1" -Port 8011
```

## Validation-Only Run
```powershell
Set-Location "c:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild"
& ".\.venv\Scripts\python.exe" ".\scripts\phase54_preview_validate.py"
```

## Preview URLs
- App: `http://127.0.0.1:8011/app?voiceDiag=1&liveVerify=1`
- Governance: `http://127.0.0.1:8011/app/operations/governance?voiceDiag=1&liveVerify=1`
- API health: `http://127.0.0.1:8011/api/health`

## What the PHASE 54 Validator Confirms
- API and frontend surfaces are reachable.
- Governance preview route is reachable.
- OpenAPI contains required PHASE 54 runtime paths:
  - `/api/health-isf/operations/runtime-state`
  - `/api/health-isf/operations/runtime-replay`
  - `/api/health-isf/operations/preview-runtime-status`
- Route registration confirms websocket route exists:
  - `/api/health-isf/ws/live/{organization_id}/{user_id}`

## Development Runtime Visibility Indicators
Visible in shell (development preview mode):
- WS status
- API status
- Hydration status
- Replay safety
- Dispatcher/Driver/Provider session counts
- DEV PREVIEW banner and dashboard runtime line

## Operational Guardrails
- Additive behavior only.
- Existing dispatch orchestration remains unchanged.
- Existing websocket contracts preserved.
- No pharmacy/medication workflow expansion in this phase.
