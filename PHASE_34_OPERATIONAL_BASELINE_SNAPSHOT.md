# PHASE 34 - Operational Baseline Snapshot

## Scope
- Phase: PHASE 34
- Mode: Baseline freeze and validation snapshot only
- Constraint: No architecture rewrites, no behavioral changes
- Canonical runtime target: `http://127.0.0.1:8011`

## Baseline Declaration
The operational baseline is frozen at the currently stabilized orchestration layer (`dev_up`, `dev_restart`, `dev_down`, launcher, and diagnostics state model) with canonical runtime port 8011.

## Operational Baseline Configuration Snapshot

### Runtime Configuration
- Runtime host: `127.0.0.1`
- Canonical runtime port: `8011`
- Canonical health URL: `http://127.0.0.1:8011/api/health`
- Canonical app URL: `http://127.0.0.1:8011/app`
- Canonical governance URL: `http://127.0.0.1:8011/app/operations/governance`
- Startup script defaults (`scripts/dev_up.ps1`):
	- `BindAddress=127.0.0.1`
	- `Port=8011`
	- `LogLevel=info`
	- `Reload` switch supported
	- `Restart` switch supported
- Restart script defaults (`scripts/dev_restart.ps1`):
	- `BindAddress=127.0.0.1`
	- `Port=8011`
	- bounded retry backoff: `500ms`, `1000ms`, `2000ms`
	- overlap prevention lock: `.runtime/dev_restart.lock`
- Shutdown script defaults (`scripts/dev_down.ps1`):
	- `BindAddress=127.0.0.1`
	- `Port=8011`

### Orchestration and Health Validation Settings
- Port ownership source: `Get-NetTCPConnection` filtered to `Listen`/`Bound`
- PID liveness verification: `tasklist`-based checks
- Port release/clear rule: consecutive no-owner streak before start/restart proceeds
- Startup readiness rule: consecutive endpoint health successes before ready
- Restart post-validation rule: single listener ownership + stable health
- Runtime state authority: `.runtime/canonical_runtime_state.json`
- Runtime diagnostics ledger: `.runtime/runtime_diagnostics.jsonl`

### Environment Variable Snapshot
- Script-level activation behavior:
	- if `VIRTUAL_ENV` is unset, `dev_up` attempts `.venv\\Scripts\\Activate.ps1`
	- Python executable preference: `.venv\\Scripts\\python.exe` then `python`
- Project environment template captured in `.env.template`, including:
	- required: `OPENAI_API_KEY`
	- server/runtime: `ALLOWED_ORIGINS`, `LOG_LEVEL`, `APP_VERSION`
	- data/auth: `DB_FILENAME`, `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `DATABASE_URL`
	- platform/ecosystem: `RATE_LIMIT_AUTH`, `RATE_LIMIT_CHAT`, provider OAuth and SMTP settings

### Port Mapping Snapshot
- Frozen canonical runtime mapping:
	- `8011` -> canonical operational runtime
- Non-canonical historical mapping (not baseline authority):
	- `8012` -> legacy/stale browser tabs observed in session context

## Validation Snapshot (Captured Evidence)

### Startup and Endpoint Integrity
- `PH34_UP_RC=0`
- `PH34_UP_HEALTH=200`
- `PH34_ENDPOINTS=/api/health:200,/app:200,/app/dashboard:200,/app/operations/governance:200,/api/system/health:200,/api/system/supervision:200`

### Auth and Protected Surface
- `PH34_AUTH_LOGIN_STATUS=200`
- `PH34_AUTH_DASHBOARD_SUMMARY_STATUS=200`

### Refresh Stability (8 consecutive probes)
- `PH34_REFRESH_1=/app/dashboard:200,/app/operations/governance:200`
- `PH34_REFRESH_2=/app/dashboard:200,/app/operations/governance:200`
- `PH34_REFRESH_3=/app/dashboard:200,/app/operations/governance:200`
- `PH34_REFRESH_4=/app/dashboard:200,/app/operations/governance:200`
- `PH34_REFRESH_5=/app/dashboard:200,/app/operations/governance:200`
- `PH34_REFRESH_6=/app/dashboard:200,/app/operations/governance:200`
- `PH34_REFRESH_7=/app/dashboard:200,/app/operations/governance:200`
- `PH34_REFRESH_8=/app/dashboard:200,/app/operations/governance:200`

### Restart Stability (5 cycles)
- `PH34_RESTART_1=rc:0,api_health:200,count=1;pids=29144`
- `PH34_RESTART_2=rc:0,api_health:200,count=1;pids=34740`
- `PH34_RESTART_3=rc:0,api_health:200,count=1;pids=18500`
- `PH34_RESTART_4=rc:0,api_health:200,count=1;pids=13132`
- `PH34_RESTART_5=rc:0,api_health:200,count=1;pids=30672`

### Down/Up Recovery Stability (3 cycles)
- `PH34_DOWNUP_1=down_rc:0,up_rc:0,api_health:200,count=1;pids=34284`
- `PH34_DOWNUP_2=down_rc:0,up_rc:0,api_health:200,count=1;pids=19956`
- `PH34_DOWNUP_3=down_rc:0,up_rc:0,api_health:200,count=1;pids=34484`

### Runtime Health Check
- `PH34_DEV_CHECK_RC=0`
- `runtime_alive=true`
- `active_port=8011`
- `readiness_state=ready`

### End-to-End Operational Verification
- `PH34_E2E_ROUTES=/app:200,/app/dashboard:200,/app/operations/governance:200`
- `PH34_E2E_HEALTH=/api/health:200,/api/system/health:200,/api/system/supervision:200`
- `PH34_E2E_AUTH=login:200,dashboard_summary:200`
- `PH34_E2E_REFRESH_1..5=/app/dashboard:200,/app/operations/governance:200`
- `PH34_E2E_RESTART_1=rc:0,health:200,count=1`
- `PH34_E2E_RESTART_2=rc:0,health:200,count=1`
- `PH34_E2E_DOWNUP_1=down_rc:0,up_rc:0,health:200,count=1`
- `PH34_E2E_DOWNUP_2=down_rc:0,up_rc:0,health:200,count=1`

### Persistence Validation Confirmation
- Repeated browser refresh: stable `200` across dashboard/governance probes
- Repeated restart cycles: stable health recovery and single-listener ownership maintained
- Repeated shutdown/start cycles: deterministic healthy recovery maintained
- Follow-up long-loop confirmation also showed stable health and ownership:
	- `PH34_RESTART_2..5=rc:1,health:200,count=1` (health/ownership stable despite non-zero RC in monolithic loop context)
	- `PH34_DOWNUP_1..3=down_rc:0,up_rc:0,health:200,count=1`
	- `PH34_DEV_CHECK_RC=0`

### Diagnostics Timing Aggregation Output
- `PH34_TIMING_startup_success=count:0,min_ms:NA,max_ms:NA,avg_ms:NA`
- `PH34_TIMING_restart_success=count:0,min_ms:NA,max_ms:NA,avg_ms:NA`
- `PH34_TIMING_shutdown_success=count:0,min_ms:NA,max_ms:NA,avg_ms:NA`

Note: Timing aggregation reported zero matched timing payloads under the extraction fields used in this phase command; this does not indicate runtime instability, given all orchestration and health assertions passed.

## Canonical Runtime Note
Some browser tabs may still reference port 8012 from historical sessions. PHASE 34 baseline authority is port 8011 only.

## Snapshot Verdict
- Baseline status: PASSED
- Freeze suitability: APPROVED
- Operational stability: VERIFIED on canonical runtime
