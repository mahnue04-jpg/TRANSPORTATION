# Deployment Lock (Do Not Expand Scope)

Status: LOCKED
Date: 2026-06-11

## Purpose
Freeze all currently working components. Only bug fixes are allowed.

## Locked Working Components
- Dispatch route shell and navigation behavior
- Existing Amicor Operations Control Center layout and button map
- Existing create flows already wired to backend APIs:
  - Create Rider
  - Create Driver
  - Create Provider
  - Create Ride
- Existing ride workflow action wiring currently present in dispatch UI
- Existing live lists rendering for Riders, Drivers, Providers, Rides
- Existing Proof Panel rendering
- Existing auth/session handling behavior
- Existing backend Health ISF endpoints currently used by dispatch page

## Change Policy
- Do not redesign UI structure.
- Do not replace pages.
- Do not introduce new modules.
- Do not rebuild rider/driver/provider architecture.
- Do not alter working components unless fixing a verified bug.
- Every bug fix must include:
  - Reproduction step
  - Root cause
  - Minimal patch scope
  - Post-fix verification evidence

## Current Execution Plan
1. PHASE 1: Persistence Verification only (must pass first)
2. PHASE 2: Driver Operations panel/actions only after PHASE 1 passes
3. PHASE 3: Maps only after PHASE 2 passes
4. PHASE 4: Revenue Readiness E2E only after PHASE 3 passes

## Verification Gate
No new development beyond bug fixes until PHASE 1 is green.
