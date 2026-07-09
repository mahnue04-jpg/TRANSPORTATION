# Production Readiness Report (Local Platform Stability)

**Generated:** 2026-07-08  
**Base URL:** http://127.0.0.1:8011  
**Artifact:** `backend/artifacts/platform_stability_report.json`

## Executive summary

Local platform stability is **operational** for end-to-end ride completion, billing handoff, and post-test server persistence. The primary instability was **not pytest** killing the server — it was lifecycle scripts using unreliable Windows `Start-Process` restarts and aggressive port-kill at test start.

| Area | Status |
|------|--------|
| Server stays up after pytest | PASS |
| Server stays up after manual ride verification | PASS |
| Full ride lifecycle + billing | PASS |
| Browser shells reachable (Driver/Rider/Dispatch/Billing/AI) | PASS |
| AI dispatch snapshot API | SLOW (30–60s); passes with extended timeout |

## Root cause: backend exits after automated tests

1. **`driver_dispatch_lifecycle_test.py` and `local_env_clean_reset.py`** call port-kill + restart at the **start** of each run (intentional clean slate).
2. **Previous restart method** used PowerShell `Start-Process -WindowStyle Hidden` with paths containing spaces (OneDrive path). This frequently failed silently → `ERR_CONNECTION_REFUSED` after the parent script exited.
3. **`SKIP_SERVER_RESTART` environment variable** was set in some shells, causing restart to be skipped while the server was down.
4. **`pytest` does not stop port 8011.** It uses an in-memory TestClient and isolated test DB (`tests/conftest.py`). Verified: same PID remains healthy after pytest.

## Fix applied

- Added `backend/scripts/server_runtime.py`:
  - Detached `subprocess.Popen` with Windows `DETACHED_PROCESS`
  - Logs to `backend/logs/uvicorn-8011.log`
  - PID file `backend/logs/uvicorn-8011.pid`
  - `ensure_server_running()` / `verify_server_persistence()`
- Lifecycle scripts now verify **`SERVER_STILL_RUNNING=true`** before PASS.
- Billing UI refresh uses `lifecycle_state`, `adminRevenue`, and `billing-handoffs` API.

## Verification performed

### Automated
- `pytest tests/test_driver_dispatch_lifecycle.py` → **PASS** (server remained up, PID unchanged)
- `python scripts/platform_stability_verification.py` → **PASS**

### Manual ride (API-driven)
Ride `cbc5f914-c1a5-4ba7-870b-0f0bc73cf014` completed with:

| Check | Result |
|-------|--------|
| Rider history shows completed | PASS |
| Driver completed-rides history | PASS |
| Driver earnings > $0 | PASS ($12.96 today) |
| Billing handoff in queue | PASS |
| Platform revenue recorded | PASS ($2.56 platform total) |
| Completed ride not in active assignments | PASS |

### Surfaces reachable after tests
- Driver: http://127.0.0.1:8011/static/ops-shell.html?platform_reset=1
- Rider: http://127.0.0.1:8011/app/riders
- Dispatch: http://127.0.0.1:8011/app/dispatch
- Billing: http://127.0.0.1:8011/app/billing
- AI Assistant: http://127.0.0.1:8011/app/ai-assistant

## Remaining issues (by priority)

### P0 — None blocking local manual operations
Server persistence and ride-to-billing flow verified on 8011.

### P1 — Performance / reliability
| Issue | Impact | Mitigation |
|-------|--------|------------|
| AI dispatch snapshot slow (30–60s) | Dispatch/AI UI may show loading or timeout on fast probes | Increase client timeout; consider caching snapshot |
| Lifecycle script runtime (~10+ min with Playwright) | Appears hung; blocks CI | Set `SKIP_BROWSER_UI=1` for API-only runs or run browser verify separately |
| `SKIP_SERVER_RESTART` in environment | Restart skipped when server down | Clear env before lifecycle runs: `$env:SKIP_SERVER_RESTART=''` |

### P2 — Configuration
| Issue | Impact |
|-------|--------|
| `JWT_SECRET` not set locally | Tokens invalid after server restart |
| SMS contact provider not configured | `contact-rider` returns 400 in tests (non-blocking) |
| `AMICOR_PUBLIC_URL` not set | Rider tracking SMS links skipped |

### P3 — Production deployment (Render)
| Issue | Impact |
|-------|--------|
| Render readiness probe uses port 8010 in some scripts | Local vs production port mismatch in legacy scripts |
| Render cold-start / readiness | Separate from local 8011 stability |

## Recommended operator workflow

```powershell
cd backend
$env:SKIP_SERVER_RESTART=''
$env:SKIP_SERVER_KILL=''
python -c "from scripts.server_runtime import ensure_server_running; ensure_server_running(force_restart=True)"
python scripts/platform_stability_verification.py
# Server remains on 8011 for browser verification
```

For full lifecycle + browser UI:
```powershell
python scripts/driver_dispatch_lifecycle_test.py
```

## Conclusion

**Local production-readiness for ride → completion → billing → revenue is PASS.**  
Platform stability issue was server **startup/restart**, not missing billing logic. Keep the detached server running on 8011 between verification runs; avoid re-running lifecycle kill/restart unless a clean reset is explicitly required.
