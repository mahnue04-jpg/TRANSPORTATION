# PHASE 33C - Canonical Persistent Runtime Ownership

## Objective

Establish a single canonical Amicor development runtime on port `8011` and make validation attach-only.

This phase stabilizes runtime ownership and developer continuity only.

## Protected Scope

Unchanged by this phase:

- governance logic
- replay logic
- policy engines
- data models
- operational shell rendering
- API contracts
- Phase 33A SPA routing behavior

## Canonical Runtime Architecture

- Canonical runtime host/port: `127.0.0.1:8011`
- Runtime owner process: `scripts/run_ops_runtime.py`
- Runtime state file: `.runtime/canonical_runtime_state.json`

The state file tracks:

- launcher PID
- uvicorn PID
- started timestamp
- active host/port
- readiness mode
- latest health check snapshot

## Startup Lifecycle

Use:

```powershell
scripts/dev_up.ps1
```

Behavior:

- probes canonical runtime health first
- reuses healthy runtime when already available
- validates PID state to prevent duplicate launches
- removes stale PID state when process is no longer alive
- starts runtime only when canonical runtime is absent

Printed URLs (canonical):

- `http://127.0.0.1:8011/app`
- `http://127.0.0.1:8011/app/operations/governance`
- `http://127.0.0.1:8011/api/health`

## Validation Attachment Model

Validation is attach-only.

Scripts:

- `scripts/check_runtime.py`
- `scripts/dev_check.py`

Rules:

- validation never spawns uvicorn
- validation never owns lifecycle
- validation fails fast with guidance when runtime is missing

## Runtime Control Commands

### Start / Reuse

```powershell
scripts/dev_up.ps1
```

### Diagnostics

```powershell
python scripts/dev_check.py
```

Provides:

- runtime alive/dead
- launcher and uvicorn PID
- uptime (from state timestamp)
- active port
- health status summary
- readiness state

### Restart

```powershell
scripts/dev_restart.ps1
```

Performs controlled shutdown then start on canonical port.

### Shutdown

```powershell
scripts/dev_down.ps1
```

Stops canonical runtime and removes stale state references.

## Expected Developer Workflow

1. Run `scripts/dev_up.ps1` once.
2. Keep browser tabs on canonical URLs (`8011`).
3. Run validations (`scripts/check_runtime.py`) repeatedly.
4. Use `python scripts/dev_check.py` when diagnosing runtime state.
5. Use `scripts/dev_restart.ps1` if runtime drifts or degrades.
6. Use `scripts/dev_down.ps1` at end of session.

## Troubleshooting Refused Connections

If browser tabs show `ERR_CONNECTION_REFUSED`:

1. Run `python scripts/dev_check.py`.
2. If runtime is down, run `scripts/dev_up.ps1`.
3. If PID exists but runtime is down, `scripts/dev_restart.ps1` will clear stale ownership.
4. Confirm browser URL uses canonical `8011`.

## Continuity Guarantees in Phase 33C

- one canonical default runtime port
- no transient validation runtime ownership
- repeated validations do not create duplicate runtimes
- runtime remains available after validation completes
- shutdown leaves no canonical listener when complete
