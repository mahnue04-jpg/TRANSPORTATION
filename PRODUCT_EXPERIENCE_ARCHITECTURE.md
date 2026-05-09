# AMICOR Product Experience + Deployment Architecture

## 1. Product Goals
- Reduce time-to-first-value with guided onboarding and first-run setup.
- Improve daily usability through conversation search, pinning, and workflow shortcuts.
- Increase operational trust with live diagnostics and deployment readiness checks.
- Preserve additive evolution: no rewrites of platform, ecosystem, or runtime layers.

## 2. UX System Additions
- New frontend module: backend/static/ux/productExperience.js
- Introduced capabilities:
  - Conversation vault with pinning and search over persisted local history.
  - Workflow center with reusable templates and execution run history.
  - Business tag inference for CRM/sales/finance/ops/support context.
  - Trust snapshot model combining diagnostics and monitor telemetry.
  - Setup completion state for first-run onboarding continuity.

## 3. UI Integration Points
- Header/Product toolbar:
  - Conversation search input and result list.
  - Pin chat toggle.
  - Workflow center toggle.
  - Trust refresh trigger.
- Workflow center panel:
  - Template creation form.
  - Template list and run history view.
- Trust strip:
  - Health state, error rate, and average latency.

## 4. Conversation Experience
- Additive enhancements over existing chat flow:
  - Message tracking through product experience controller.
  - Searchable snippets by role and conversation title.
  - Pin state persisted across refresh for active session namespace.
  - Consecutive role grouping in message rendering for visual clarity.

## 5. Workflow Center
- UI-level workflow orchestration model:
  - Save named templates with prompt and action chain descriptors.
  - Execute templates with deterministic status and duration records.
  - Persist and replay run history to support operational continuity.
- Backward compatible with existing backend ecosystem workflow APIs.

## 6. Trust Layer
- Trust snapshot combines:
  - Runtime diagnostics summary (request count, error rate, latency)
  - Production monitor heartbeat status
- Health state model:
  - healthy
  - degraded
  - critical
- Human-readable hints emitted for elevated latency/error conditions.

## 7. Deployment Quality System
- New deployment preflight utility: backend/static/deployment/preflight.js
- Validates:
  - Cloud deployment config presence (Render/Railway/Fly/Docker/Procfile)
  - Health endpoint declarations in backend app shell
  - Startup command availability for process launch
- Produces operational guidance:
  - SSL/TLS hardening recommendations
  - Backup and restore strategy checklist

## 8. Validation and Benchmarks
- New UX validation entrypoint:
  - npm run test:ux
- Extended deployment validation:
  - npm run test:deployment now includes deployment preflight checks
- New frontend benchmark entrypoint:
  - npm run benchmark:frontend

## 9. Mobile + PWA Continuity
- Existing service worker and manifest preserved.
- New controls are mobile-safe and additive to current responsive layout.
- No breaking changes to offline/static cache behavior.

## 10. Operational Constraints
- Zero replacement of established platform/ecosystem/runtime systems.
- Additive, scoped modules with storage fallback for constrained environments.
- Frontend features fail soft when optional diagnostics modules are absent.
