# AMICOR PRODUCT AUDIT

Date: 2026-05-09
Scope: Full product audit and real-app validation (no architecture rewrite, no new major subsystems).

## Executive Summary
Amicor is runnable and broadly test-covered, with strong backend uptime, health endpoints, upload constraints, and tool routing. Core MVP blockers remain in product-layer behavior: authentication is not exposed in the running app/backend surface, conversation session restoration is not preserved in the current UI refresh flow, and several requested capability experiences are generic-text responses rather than dedicated product workflows.

Overall readiness: **Partially ready** (not yet MVP-ready).

## Evidence Run Log
Required test commands executed:

- `npm test` -> pass (147 passed, 0 failed)
- `npm run test:production` -> pass (96 passed, 0 failed)
- `npm run test:auth` -> pass (97 passed, 0 failed)
- `npm run test:conversation` -> pass (10 passed, 0 failed)
- `npm run test:capabilities` -> pass (9 passed, 0 failed)
- `npm run test:deployment` -> pass (72 passed, 0 failed)

Additional validation:

- `& ".\.venv\Scripts\python.exe" backend/scripts/validate_startup.py` -> pass after dependency install
- `bash scripts/health_check.sh` -> failed on this Windows host (`bash` not installed), endpoint checks were validated manually
- Browser runtime check on `http://127.0.0.1:8000/app` -> no page errors and no console errors on reload

## Audit Matrix

### 1) App startup
Status: **Partially working**

What works:
- Backend starts cleanly with FastAPI lifespan and startup validation.
- Frontend app shell loads at `/app`.
- No fatal browser console/page errors observed on reload.
- No broken imports observed during startup.

What is broken / risk:
- Environment warnings present by default (`ALLOWED_ORIGINS=*`, missing `APP_VERSION`, default DB path).
- Startup validation initially failed on missing packages in local venv before installing requirements.

Severity: **Medium**

### 2) Authentication flow
Status: **Broken for product surface**

What works:
- Auth test suite exists and passes (`npm run test:auth`).

What is broken:
- Running backend route surface does not expose signup/login/logout/session endpoints in `backend/app/main.py`.
- Running UI shows no login/signup/logout controls in `backend/static/index.html`.

Severity: **Critical**

### 3) Conversation flow
Status: **Partially working**

What works:
- User can send a message and receive response.
- Tool badge renders in UI responses (example: `news`).
- Typing/loading state appears during request.

What is broken / partial:
- No explicit user-facing cancel button for in-flight chat request observed.
- Conversation messages were not restored in UI after full page refresh during live test.
- Streaming UX is partly represented by typing indicator; explicit chunk streaming behavior was not observed in live network path.

Severity: **High**

### 4) Memory flow
Status: **Partially working**

What works:
- Backend stores/retrieves recent history per `user_id` through router path.
- `/api/reset` clears memory by `user_id`.
- Memory tests pass (`npm run test:memory`).

What is partial:
- Session restoration in UI after refresh did not retain visible conversation in live validation.
- Memory context injection is capability-dependent and not always visible to end user.

Severity: **High**

### 5) Workflow flow
Status: **Partially working**

What works:
- Capability/tool routing works (`weather`, `news`, `search`, `business`, `education`, `openai`).
- Retry UX exists for failed response bubbles.

What is broken / partial:
- Dedicated workflow timeline UI was not observed in the running app shell.
- Retry/cancel/recovery exists at message-error level, but full workflow state lifecycle UX appears limited.

Severity: **Medium**

### 6) Tool flow
Status: **Working with caveats**

What works:
- Safe tools execute and return responses.
- Tool activity is visible in UI via tool labels on assistant messages.
- Tool errors are surfaced and recoverable (retry button, status updates).

What is partial:
- Permission enforcement model is not clearly surfaced in current UI for end users.

Severity: **Medium**

### 7) File/document flow
Status: **Working**

What works:
- Upload UI works (attach button, preview chip, remove control).
- Document text extraction works and is used in next prompt.
- Invalid type handling works (`415` / UI warning).
- Oversize handling works (`10 MB` max, UI warning for large files).
- Retry-related infrastructure exists in error recovery module.

Severity: **Low**

### 8) Capability flow
Status: **Partially working**

What works:
- Research assistant routing works but depends on external key (search returned clear missing-key message).
- Business summary flow works via `business` tool.

What is partial / weak:
- Task workflow and report generation intents returned generic long-form text, not a clearly structured dedicated workflow experience.
- Document workflow relies on prompt+upload context rather than a distinct end-to-end document pipeline UX.

Severity: **Medium**

### 9) Production readiness
Status: **Partially working**

What works:
- All requested npm test suites pass.
- Startup validation passes in configured environment.
- `/api/health` and `/api/health/detail` pass.
- Monitoring hooks do not crash in runtime checks and production tests.

What is partial:
- `scripts/health_check.sh` requires bash; not portable on this Windows environment as-is.
- Startup warnings indicate production env defaults still in use.

Severity: **Medium**

### 10) UX audit
Status: **Partially working**

What works:
- First-load onboarding appears.
- Loading/typing and input-lock patterns are present.
- Upload UX and inline tool labeling are clear.
- Mobile viewport (375x812) renders without immediate fatal breakage.

UX issues observed:
- Conversation is not restored after refresh in visible chat area.
- No clear explicit cancel action for in-flight chat request in primary UI.
- Capability actions are mixed between true workflows and generic text responses, which can feel inconsistent.

Severity: **High**

## What Works
- Backend startup/lifespan and health endpoints.
- Core chat request/response loop.
- Tool routing and tool-tagged responses.
- Upload validation and context injection.
- Error recovery hooks, skeleton/input lock, and monitoring hooks.
- Broad automated test coverage and passing suites.

## What Is Broken
- Product-surface authentication flow (signup/login/logout/session restore) is not present in currently running backend/UI surface.
- Conversation restore on page refresh failed in live validation.

## What Is Partially Working
- Workflow lifecycle UX (state/timeline/cancel) is only partly visible.
- Capability depth for task/report/document workflows is inconsistent.
- Production portability of shell health script on Windows host.

## Must Fix Before MVP
1. Add/enable real product authentication surface (signup/login/logout/session restore) in live UI+API path.
2. Ensure conversation/session restoration is deterministic after refresh.
3. Add explicit cancel control for in-flight requests and validate interruption path.
4. Standardize capability workflows so task/report/document/research are productized experiences, not just generic text fallback.
5. Harden production env defaults (origins/version/log level) and provide cross-platform health-check command.

## Severity Register
- **Critical**: Authentication flow missing from live product surface.
- **High**: Conversation persistence after refresh not retained in live UX.
- **High**: UX consistency gaps for cancel/recovery/workflow confidence.
- **Medium**: Production env warnings/defaults and script portability.
- **Medium**: Capability depth inconsistency.
- **Low**: Minor polish and messaging consistency items.

## Recommended Fix Order
1. Implement/enable end-to-end auth in live UI/API path and verify session restore/expiry UX.
2. Fix conversation restore behavior after page refresh for same user/session.
3. Add visible cancel/interruption control and verify resumed state handling.
4. Productize capability workflows (document/task/report/research) with deterministic UI stages.
5. Resolve production config warnings and add Windows-compatible health-check command/script.
6. Run full regression suite + live browser checklist and re-issue MVP signoff audit.
