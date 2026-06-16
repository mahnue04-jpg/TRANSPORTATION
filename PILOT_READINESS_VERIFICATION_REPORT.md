# Pilot Readiness Verification Report

Date: 2026-06-04
Scope: Health ISF pilot launch-blocker closure verification (only two reported defects)
Operator role: dispatcher
Runtime: http://127.0.0.1:8011

## Summary Verdict

Recommendation: Go for pilot launch.

Reason: Both launch-blocking defects were reproduced, root-caused, fixed with minimal scoped changes, and revalidated in live operator verification without guest fallback or rides initialization failure.

## Defect 1: Dispatcher Session Instability (401/429 Churn, Guest Fallback)

### Reproduction (Pre-fix)

1. Authenticate as dispatcher.
2. Trigger sustained auth-refresh pressure (same runtime path used by guarded route/session recovery).
3. Observe refresh endpoint returning `429` and subsequent session invalidation.
4. Session drops to guest and guarded routes lock (`authGateVisible: true`).

### Root Cause

- `backend/static/ux/sessionManager.js` treated refresh rejection as terminal and cleared session state during refresh churn.
- Under refresh throttling/rejection conditions, this forced operator logout and route guard fallback.

### Minimal Fix Applied

- File changed: `backend/static/ux/sessionManager.js`
- Updated refresh failure handling in `_refreshAccessTokenInner(...)`:
  - Do not clear active session on refresh failure responses.
  - Emit telemetry events (`amicor:session-refresh-throttled`, `amicor:session-refresh-rejected`) and return `false` to allow graceful recovery logic.

### Validation (Post-fix)

- Re-ran sustained refresh pressure (45 forced refresh attempts).
- Observed intermittent `ok=false` refresh results under throttle/rejection, but:
  - `active` remained `true`
  - role remained `dispatcher`
  - no guest fallback occurred.
- Re-ran guarded route transitions (`dashboard`, `dispatch`, `rides`) repeatedly:
  - `authGateVisible` remained `false`
  - `websocketStatus` remained `connected`
  - no `401/429`-driven session drop.

## Defect 2: Intermittent "Frontend failed to initialize" in Rides Workspace

### Reproduction (Pre-fix)

1. Trigger a startup asset error event in the Health ISF shell startup path.
2. Observe immediate fatal startup state:
  - fatal banner visible: `Frontend failed to initialize. Check console.`
  - `fatal: true`
  - `criticalFailures` populated.

### Root Cause

- `backend/static/index.html` startup preflight failed hard on the first script/link asset error.
- A single transient load failure could immediately trip fatal initialization state instead of allowing a retry.

### Minimal Fix Applied

- File changed: `backend/static/index.html`
- Added one-time retry behavior for same-origin `/static/*` script/link startup assets before invoking fatal startup failure.
- Persistent repeated failure still escalates to fatal state (safety preserved).

### Validation (Post-fix)

- Single transient startup asset error now results in:
  - `fatal: false`
  - fatal banner not visible.
- Repeated error on the same asset still results in:
  - `fatal: true`
  - fatal banner visible.
- Confirms transient-failure tolerance without masking genuine persistent startup faults.

## Live Operator Re-Verification

After applying both fixes, live operator verification was re-run on the active runtime:

1. Dispatcher session active and stable.
2. Route sequence (`dispatch` -> `rides` -> `dashboard` -> `rides` -> `dispatch`) remained authenticated throughout.
3. No guest fallback observed.
4. No fatal frontend initialization banner observed on rides route.
5. Realtime continuity remained healthy (`websocketStatus: connected`).

## Go / No-Go Recommendation

Go.

Launch-blocking conditions from this report are closed:

1. Dispatcher session now survives guarded route changes without guest fallback.
2. Rides workspace no longer trips fatal startup state on a single transient asset failure.