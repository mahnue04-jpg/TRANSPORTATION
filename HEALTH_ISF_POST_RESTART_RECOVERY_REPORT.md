# Health ISF Post-Restart Recovery Report

Generated: 2026-06-09 (local) / 2026-06-10T03:38Z (runtime UTC)
Scope: Recovery and verification only (no feature development)
Canonical runtime: http://127.0.0.1:8010

## 1) Recovery Action Executed
- Script run: scripts/phase54_preview_up.ps1 -HostName 127.0.0.1 -Port 8010 -StopConflictingPreviewRuntimes
- Result: PASS
- Evidence:
  - "Canonical runtime is ready"
  - /api/health = 200
  - /app = 200
  - /app/operations/governance = 200
  - PHASE 54 validator success=true
  - Alternate port probe 8011 refused connection

## 2) Running Services
- Backend API runtime: RUNNING
  - Evidence: /api/health returned 200
  - Evidence: state file .runtime/canonical_runtime_state.json shows mode=running, ready=true, host=127.0.0.1, port=8010
- Runtime governor service: RUNNING
  - Evidence: /api/system/health payload runtime_governor.status=alive
- Memory persistence service: RUNNING
  - Evidence: /api/system/health payload memory_persistence.status=healthy
- WebSocket service: RUNNING
  - Evidence: /api/system/health payload websocket.status=healthy
- Frontend serving layer: RUNNING (served by backend runtime)
  - Evidence: /app returned 200, page title "Amicor Nova Operational Platform"

## 3) Failed Services
- None detected in runtime health payload.
- Evidence:
  - backend_status=green
  - tests.failed=0 in /api/system/health
  - No failing component status reported in runtime summary checks

## 4) URLs and Platform Verification (PASS/FAIL)

| Target | URL | HTTP | Screen Evidence | Result |
|---|---|---:|---|---|
| Operations Platform | http://127.0.0.1:8010/app/operations | 200 | Browser snapshot title "Amicor Nova Operational Platform" and route section loaded | PASS |
| Driver Platform | http://127.0.0.1:8010/app/drivers | 200 | Browser snapshot heading "Drivers" | PASS |
| Provider Platform | http://127.0.0.1:8010/app/providers | 200 | Browser snapshot heading "Providers" | PASS |
| Customer/Rider Platform | http://127.0.0.1:8010/app/riders | 200 | Browser snapshot heading "Riders / Patients" | PASS |
| Customer alias | http://127.0.0.1:8010/app/customer | 200 | Browser snapshot resolves to Riders/Patients surface | PASS |

Additional route checks:
- /app = 200
- /app/patients = 200
- /app/customers = 200

## 5) Ports

| Port | Status | Evidence |
|---:|---|---|
| 8010 | LISTENING | netstat shows listener on 127.0.0.1:8010 owned by python.exe (PID 2552) |
| 8011 | NOT LISTENING | netstat check = NOT LISTENING; validator alternate-port probe refused |
| 8000 | NOT LISTENING | netstat check = NOT LISTENING |
| 5432 | NOT LISTENING | netstat check = NOT LISTENING |

## 6) Database Status

- Runtime database health endpoint: PASS
  - Evidence: /api/health/detail -> db.ok=true
  - Evidence: db_path=C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild\backend\data\chat.db
- Direct DB connectivity check: PASS
  - Evidence query result:
    - db_file: c:/Users/smoni/OneDrive/New folder/New folder/Amicore_Rebuild/backend/data/chat.db
    - query_ok: true
    - table_count: 124

## 7) Backend Service Verification Summary

| Check | Evidence | Result |
|---|---|---|
| API liveness | /api/health = 200 | PASS |
| Detailed health | /api/health/detail = 200 and db.ok=true | PASS |
| System runtime health | /api/system/health backend_status=green | PASS |
| Runtime governor | runtime_governor.status=alive | PASS |
| Memory persistence | memory_persistence.status=healthy | PASS |
| WebSocket subsystem | websocket.status=healthy | PASS |

## Final Recovery Verdict
- Environment recovery after Windows restart: PASS
- Operations Platform: PASS
- Driver Platform: PASS
- Provider Platform: PASS
- Customer/Rider Platform: PASS
- Database connectivity: PASS
- Failed services: NONE OBSERVED
