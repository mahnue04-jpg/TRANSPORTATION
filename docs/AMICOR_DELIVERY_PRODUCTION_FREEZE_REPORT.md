# AMICOR Delivery — Production Readiness & Freeze Report

**Date:** 2026-09-08  
**Software status:** **A. READY TO FREEZE**  
**Stripe mode:** TEST only (LIVE not enabled)  
**Driver 001:** Not deleted, reset, replaced, or duplicated  

AMICOR DELIVERY PRODUCTION BUILD FROZEN — no further changes unless required by a verified bug, compliance requirement, or launch-critical business need.

## What this freeze covers

Delivery operations run on the shared Health ISF backend and Render service. This pass cleaned **user-facing Delivery branding and a launch-blocking frontend crash**, then verified health, routes, billing idempotency tests, and Driver 001 safety tests. It did **not** rename backend modules or migrate the Render hostname.

## Tests performed

| Area | Result |
|------|--------|
| Delivery ops-shell branding contract | PASS (`test_delivery_ops_shell_branding.py`) |
| Undefined Delivery helper stubs present | PASS |
| Driver apply HTML/resume contract | PASS |
| Nova/ops-shell cache-bust alignment | PASS |
| Financial completion / duplicate billing | PASS (`test_financial_engine_completion.py`, `test_executive_revenue_regression.py`) |
| Driver 001 duplicate / prep / token reissue | PASS (targeted suite; 33 passed, 2 skipped on last full targeted run after HTML assertion update) |
| Completed-ride mobile cleanup | PASS (`test_driver_mobile_lifecycle_cleanup.py`) |
| Production `GET /api/health` | PASS HTTP 200 |
| Production `GET /api/health/live` | PASS HTTP 200, deploy `a1a014958d28` on `main` |
| Production `GET /api/health/readiness` | PASS score 100 |
| Production `GET /api/health/detail` | PASS PostgreSQL healthy |
| Production routes `/app`, `/app/riders`, `/app/mobile`, `/app/dispatch`, `/app/billing`, `/platform-ops/driver-apply` | PASS HTTP 200 |
| Deployed private-pay Stripe TEST E2E (this session) | NOT RE-RUN — no production seed password in this environment; prior path remains frozen |
| Driver 001 production GET (this session) | NOT RE-RUN — admin JWT not available; local safety tests pass and no mutation scripts were executed |

## Bugs found

1. **Launch-blocking:** `ops-shell.js` called `captureDeliveryProofDrafts`, `takeLiveDeliveryForm`, `putLiveDeliveryForm`, `renderDeliveryOfferCardsHtml`, and `renderDeliveryActiveJobCardHtml` on every page render, but those functions were never defined. This throws `ReferenceError` and can blank Delivery ops screens including driver mobile.
2. **Branding:** Delivery-facing ops-shell, customer request, driver mobile, dispatch, billing, and driver apply surfaces displayed Health / patient / NEMT wording.
3. **Resume guard:** After a first create, `existingApplicationLoaded` stayed false until a later hydrate, so the first save could treat the new draft as empty-field-unsafe.
4. **Admin PATCH complete vs driver complete:** `update_ride_status` still does not share the driver `dropoff_complete` assignment-close path, and `RideLifecycleManager` rejects `in_progress → completed`. Left unchanged to avoid touching the frozen trip-lifecycle engine.

## Bugs fixed

1. Added no-op Delivery helper stubs so page renders cannot crash.
2. Rebranded Delivery-facing ops-shell / driver apply / onboarding admin / PWA manifest copy to **AMICOR Delivery** without renaming APIs or Health ISF modules.
3. Set `existingApplicationLoaded = true` immediately after a successful draft create.
4. Cache-busted ops-shell and driver-apply assets (`20260908.1`).

## Files changed

- `backend/static/ops-shell.js`
- `backend/static/ops-shell.html`
- `backend/static/platform-ops/driver-apply.html`
- `backend/static/platform-ops/driver-apply.js`
- `backend/static/platform-ops/driver-onboarding-admin.html`
- `backend/static/manifest.webmanifest`
- `backend/app/runtime_contract.py`
- `backend/tests/test_delivery_ops_shell_branding.py` (new)
- `backend/tests/test_driver_apply_resume_hydration.py`
- `backend/tests/test_nova_full_shell_uat.py`
- `backend/tests/test_simple_driver_application.py`
- `backend/tests/test_driver_work_setup.py`
- `.cursor/rules/amicor-delivery-freeze.mdc` (new)
- `docs/AMICOR_DELIVERY_PRODUCTION_FREEZE_REPORT.md` (this file)

## Database changes

None. No migrations. No Driver 001 writes. No payment schema changes.

## Routes verified

| Route | Role | Notes |
|-------|------|--------|
| `/app` | Home / launcher | Delivery operations title |
| `/app/riders` | Customer delivery request | Display copy only; API remains `/api/health-isf/customer-requests` |
| `/app/mobile` | Driver mobile | Delivery workflow labels; same lifecycle actions |
| `/app/dispatch` | Dispatch | Delivery queue labels |
| `/app/billing` | Billing / earnings | Claims wording removed from display |
| `/app/trips` | History | Nav label Deliveries |
| `/platform-ops/driver-apply` | Driver application | AMICOR Delivery title; resume/session unchanged |
| `/platform-ops/driver-onboarding-admin` | Admin onboarding | Title only |
| `/workspace` Health ISF | Health | Left as AMICOR Health |
| Marketing `/` | Public Health site | Left as AMICOR HEALTH ISF LLC |

## Hostname / infrastructure (later, not this freeze)

Production remains:

- Service: `amicor-health-isf`
- URL: `https://amicor-health-isf-py.onrender.com`

A later, planned hostname split (for example `amicor-delivery` vs Health) should be a dedicated, low-risk cutover with CORS, `AMICOR_PUBLIC_URL`, Stripe return URLs, and webhook endpoints updated together. Do not migrate that in this freeze.

## Known non-launch-blocking software issues

- Public marketing site still describes AMICOR Health / NEMT (intentionally not redesigned).
- Medical coordinator, grants, and `/workspace` Health ISF remain Health-branded.
- Footer still links “Rider App” on the marketing site.
- Admin status-complete path is not the canonical completion path; driver route-progress is.
- Some local assignment-reconciliation tests can fail when auto-dispatch races the test assign (pre-existing; not introduced by this pass).
- Deployed Stripe TEST revenue E2E was not re-executed in this session.

## External business / compliance items (not software)

These remain outside the software freeze and can still block legal launch:

- MnDOT clarification
- USDOT
- Motor Carrier of Property registration
- Correct insurance
- Form E
- Hennepin / Ramsey clarification
- Driver compliance requirements (background, credentials, renewals)

## Safety confirmations

- Stripe remains TEST.
- Driver 001 application/documents were not modified.
- AMICOR Health backend module names, APIs, and marketing site were not renamed.
- Private-pay checkout, webhook, and `financial_engine.py` were not changed.
- AMICOR Nova feature work was not started.
