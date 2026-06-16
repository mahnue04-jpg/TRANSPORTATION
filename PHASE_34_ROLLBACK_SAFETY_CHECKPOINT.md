# PHASE 34 - Rollback Safety Checkpoint

## Purpose
Define the known-good rollback checkpoint aligned with PHASE 34 operational baseline freeze.

## Known-Good Target
- Canonical runtime URL: `http://127.0.0.1:8011`
- Runtime health expectation: `/api/health` returns `200`
- Listener ownership expectation: exactly one listener on port `8011`

## Known-Good Runtime State Snapshot
- `runtime_alive=true`
- `readiness_state=ready`
- `active_port=8011`
- `dev_check` return code: `0`
- Critical route availability: `/app`, `/app/dashboard`, `/app/operations/governance` all `200`
- System health availability: `/api/system/health` and `/api/system/supervision` both `200`

## Checkpoint Artifacts
- `scripts/dev_up.ps1`
- `scripts/dev_restart.ps1`
- `scripts/dev_down.ps1`
- `scripts/run_ops_runtime.py`
- `scripts/dev_check.py`
- `.runtime/canonical_runtime_state.json`
- `.runtime/runtime_diagnostics.jsonl`
- `PHASE_34_OPERATIONAL_BASELINE_SNAPSHOT.md`
- `PHASE_34_STABILIZATION_REPORT.md`

## Rollback Triggers
- Reappearance of multi-owner listener state on port `8011`
- Restart cycles return non-zero or fail to restore `api_health=200`
- `scripts/dev_check.py` returns non-zero under canonical runtime conditions
- Sustained endpoint regressions for `/app`, `/app/dashboard`, or `/app/operations/governance`

## Rollback Procedure (Operational)
1. Stop runtime using `scripts/dev_down.ps1`.
2. Restore checkpointed runtime orchestration files.
3. Start canonical runtime using `scripts/dev_up.ps1`.
4. Validate with `scripts/dev_check.py` and endpoint probes.
5. Confirm single listener ownership on port `8011`.

## Post-Rollback Acceptance Criteria
- `dev_up` returns success and health is `200`
- `dev_check` reports `runtime_alive=true`, `readiness_state=ready`, `active_port=8011`
- Port ownership remains single-process for listener state

## Freeze Integrity Statement
This checkpoint preserves the stabilized PHASE 34 behavior without introducing architecture changes. It is suitable as the rollback anchor for subsequent development phases.

## Orchestration Freeze Marker
The runtime orchestration layer is explicitly frozen at this checkpoint for:
- startup orchestration behavior
- restart lifecycle behavior
- shutdown and listener cleanup behavior
- PID ownership and health-readiness verification behavior
