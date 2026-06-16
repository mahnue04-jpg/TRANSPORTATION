# PHASE 43 - ISF MVP and Grant Proof Report

## Objective
Launch Health ISF MVP workflows for pilot transportation operations and establish June 15 rural transportation grant readiness evidence.

## Completed Workflows
- Driver onboarding foundation (persistent backend + operational UI):
  - Driver application create/list lifecycle endpoints.
  - Review lifecycle actions: applied, pending_review, approved, active, suspended.
  - Document reference placeholders for license, insurance, registration.
  - Background authorization and service category capture.
- Recurring transportation template engine:
  - API endpoint to surface recurring schedule templates from persisted ride patterns.
  - Grant view renders recurring templates with category, schedule days, pickup time, and route context.
- Grant readiness snapshot endpoint:
  - Aggregates rides, onboarding queue, recurring templates, screenshot checklist, and readiness metrics.
- Phase 43 seed workflow:
  - Adds recurring transportation scenarios.
  - Adds onboarding candidates with mixed lifecycle states.
  - Safe to run repeatedly (duplicate-guarded).
- UI expansion in production Health ISF shell:
  - New Onboarding tab for submission + review queue operations.
  - New Grant Proof tab for metrics + screenshot inventory + recurring evidence panels.

## Screenshot Inventory (Operationally Capturable)
- Dispatch Live Queue (existing ride operations panel).
- Driver Onboarding Review (new onboarding panel with lifecycle actions).
- Recurring Transportation Templates (new grant proof recurring section).
- Grant Metrics Overview (new readiness metric grid).

## Remaining Gaps
- Document upload workflows are placeholders only (reference fields), not binary upload storage.
- Background check integration is authorization-state only; no external screening provider integration.
- Notification persistence remains in existing operational event surfaces; dedicated grant-focused notification ledger can be added later.
- Geospatial driver map remains represented by existing operational diagnostics rather than a dedicated grant map canvas.

## June 15 Readiness Status
- Transportation workflow readiness: READY (dispatch, lifecycle, provider/driver operations already established).
- Onboarding workflow readiness: READY (application + review queue lifecycle).
- Recurring operations readiness: READY (templates surfaced and seed scenarios available).
- Grant artifact readiness: READY WITH OPERATIONAL CAPTURE (screenshot-ready panels now available).

## Deployment Priorities
1. Run `/api/health-isf/ops/seed-phase43` in target environment.
2. Validate onboarding status transitions with admin and dispatcher roles.
3. Capture screenshot bundle from Onboarding + Grant Proof + Dispatch views.
4. Export metrics snapshot from `/api/health-isf/grant-proof/snapshot` for grant packet appendices.
5. Optionally add document upload storage and external background check integration before pilot scale-up.

## Changed Areas
- backend/app/modules/health_isf/models.py
- backend/app/modules/health_isf/schemas.py
- backend/app/modules/health_isf/service.py
- backend/app/modules/health_isf/routes.py
- backend/static/index.html
- backend/static/modules/health_isf/health-isf.js
- backend/static/modules/health_isf/health-isf.css
