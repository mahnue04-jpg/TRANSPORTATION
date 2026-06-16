# PHASE 33B - Runtime Orchestration Stabilization

## Purpose

Phase 33B stabilizes runtime and process orchestration for Amicor so backend APIs and SPA shell routes remain available after startup and after validation checks complete.

This phase is process-lifecycle focused only.

## Non-Goals (Protected Behavior)

The following areas are intentionally unchanged:

- Governance scoring logic
- Replay logic
- Policy evaluation behavior
- Operational data models
- API contracts
- Phase 33A routing behavior
- Canonical `/app` routing
- API/static fallback protections

## Architecture

### Runtime Owner

- Script: `scripts/run_ops_runtime.py`
- Owns uvicorn process lifecycle
- Streams subprocess logs continuously
- Polls readiness and runtime health
- Detects crashes and emits diagnostics
- Handles Ctrl+C / termination signals gracefully

### Validation Consumer

- Script: `scripts/check_runtime.py`
- Read-only verifier
- Never starts or stops uvicorn
- Confirms runtime surface is healthy and contract-preserving

## Runtime Lifecycle Ownership

1. Operator starts runtime with `scripts/start_backend.ps1` or `scripts/start_backend.bat`
2. Launcher starts uvicorn in `backend` directory
3. Launcher waits for readiness checks:
   - `/api/health`
   - `/app`
   - `/app/operations/governance`
4. Launcher remains alive and continues health polling until shutdown signal
5. Validation (`scripts/check_runtime.py`) can run at any time without owning process lifecycle
6. Ctrl+C triggers graceful shutdown and subprocess termination diagnostics

## Startup Sequence

### PowerShell

```powershell
scripts/start_backend.ps1
```

Optional overrides:

```powershell
scripts/start_backend.ps1 -Host 127.0.0.1 -Port 8012 -LogLevel info -Reload
```

### Batch

```bat
scripts\start_backend.bat
```

## Runtime Configuration

Environment variables supported by the launcher:

- `AMICOR_HOST` (default `127.0.0.1`)
- `AMICOR_PORT` (default `8012`)
- `AMICOR_RELOAD` (`1/true/yes/on` enables reload, default disabled)
- `AMICOR_LOG_LEVEL` (default `info`)

Additional orchestration tuning:

- `AMICOR_STARTUP_TIMEOUT` (seconds, default `90`)
- `AMICOR_HEALTH_INTERVAL` (seconds, default `10`)

## Validation Flow

Run while runtime is already active:

```powershell
python scripts/check_runtime.py
```

Checks performed:

- Backend reachable (`/api/health` -> JSON 200)
- SPA shell reachable (`/app` -> HTML 200)
- Governance shell route reachable (`/app/operations/governance` -> HTML 200)
- Legacy route redirect (`/operations/governance` -> `/app/operations/governance`)
- Invalid API path returns JSON 404
- Invalid asset path returns 404 and does not return SPA shell HTML
- Runtime still reachable at end of validation

## Expected Runtime URLs

- `http://127.0.0.1:8010/app`
- `http://127.0.0.1:8010/app/operations/governance`
- `http://127.0.0.1:8010/api/health`

## Troubleshooting

### Startup timeout

Symptoms:

- `runtime.readiness.timeout` log event

Actions:

- Confirm no stale process owns `AMICOR_PORT`
- Increase `AMICOR_STARTUP_TIMEOUT`
- Check emitted `runtime.log` lines for import/startup failures

### Subprocess crash after startup

Symptoms:

- `runtime.crash.detected` log event

Actions:

- Inspect preceding streamed log lines
- Validate backend imports: `python -m compileall backend`

### Validation failures

Symptoms:

- `scripts/check_runtime.py` reports `OVERALL=FAIL`

Actions:

- Ensure runtime launcher is still active in separate terminal
- Check route contract in responses:
  - API paths should not return shell HTML
  - Asset misses should return 404

## Common Failure Modes

- Port conflict on configured runtime port
- Runtime launched from wrong working directory (must resolve `backend/app/main.py`)
- Environment mismatch when not using project virtual environment
- Stale process confusion where checks target old server instance
