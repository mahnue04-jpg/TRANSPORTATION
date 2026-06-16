# STABILIZATION WEEK - PRIORITY A.4

## Scope
- API-only operational readiness validation on a clean migrated database.
- Startup hardening for post-reboot/login/sleep-wake reliability.
- No direct DB writes for business flow setup; public APIs only.

## Environment
- OS: Windows PowerShell
- Runtime target: FastAPI production mode (no reload) on port 8000
- Clean DB target: `backend/pilot_a4_clean.db`

## Part 1 - API-Only E2E Validation

### Evidence Artifacts
- JSON evidence: `A4_OPERATIONAL_EVIDENCE.json`
- Runtime logs: `.runtime/canonical_runtime.out.log`

### Executed API Surface
- Auth: register/login
- Onboarding: providers, drivers, vehicles
- Rider flow: customer-requests
- Dispatch lifecycle: assign/driver actions
- Idempotency check: duplicate key on rides create
- Recurring scheduling: recurring schedule create
- Authorization check: rider blocked from write endpoint

### Results
- Pilot readiness: FAIL

### Blocking Findings
1. Fresh tenant creation blocker (RBAC/tenant model mismatch):
   - Newly registered rider tenant resolves to the same organization as dispatcher in validation evidence.
   - Evidence: `fresh_tenant_validation` failure in `A4_OPERATIONAL_EVIDENCE.json`.

2. Operational lifecycle blocker in API-only run:
   - Driver assignment/lifecycle failed when driver status was unavailable/offline in first comprehensive run.
   - Evidence: 400 responses for assign/accept/progress in `A4_OPERATIONAL_EVIDENCE.json`.

3. Startup/runtime path stability issue discovered during restart loops:
   - Intermittent auth/register/login 500 errors with `sqlite3.OperationalError: unable to open database file` due relative SQLite URL resolution after restarts.
   - Evidence: correlation IDs and trace in `.runtime/canonical_runtime.out.log`.

## Part 2 - Startup Hardening

### Implemented
- Production watchdog supervisor:
  - `scripts/amicor_runtime_watchdog.ps1`
- One-command production controls:
  - `scripts/start_amicor_prod.ps1`
  - `scripts/stop_amicor_prod.ps1`
- Startup task automation:
  - `scripts/install_amicor_startup_task.ps1`
  - `scripts/uninstall_amicor_startup_task.ps1`
- Runtime self-probe hardening:
  - `scripts/run_ops_runtime.py` uses loopback probe host when bind host is `0.0.0.0`.
- SQLite URL hardening in watchdog:
  - Relative `sqlite:///./...` is normalized to absolute path before runtime launch.

### NPM Commands Added
- `prod:start`
- `prod:stop`
- `prod:install-startup-task`
- `prod:uninstall-startup-task`
- `validate:a4`

### Recovery Verification
- Controlled crash simulation performed by killing uvicorn process.
- Observed: watchdog detected crash and relaunched runtime with new launcher/uvicorn PIDs.
- Health recovered to 200 after watchdog restart window.

## Limitations
- Physical reboot and sleep/wake actions were not executed interactively in this session.
- Reboot/login automation is configured via Windows Scheduled Task scripts but requires host-level execution context to fully validate.

## Current Assessment
- Startup hardening implementation is in place and crash-recovery behavior was observed.
- Pilot operational readiness remains FAIL due tenant/RBAC onboarding path constraints and lifecycle/runtime issues observed in strict API-only validation.
