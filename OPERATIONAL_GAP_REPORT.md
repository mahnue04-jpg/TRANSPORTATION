# Operational Gap Report

**Objective:** Identify the shortest path from current state to a real revenue-producing transportation operation.

**Source:** [OPERATIONAL_TRUTH_REPORT.md](OPERATIONAL_TRUTH_REPORT.md)

**Scope:** Only operational gaps in the revenue chain:
Rider -> Trip -> Driver -> Vehicle -> Dispatch -> Completion -> Billing -> Revenue

**Important:** No implementation work is proposed here. This is a gap ranking and execution priority document only.

---

## Executive Priority

**Next highest-value operational gap:** Vehicle assignment.

**Why this is next:** The platform already has usable rider intake, trip creation, driver assignment, dispatch, completion, and payment ledger surfaces. The shortest path to a real transportation business is to close the vehicle leg so trips are tied to actual fleet assets, not just placeholder fleet views. Billing remains a major revenue gap, but vehicle assignment is the nearer operational blocker in the chain.

---

## Ranked Gap List

### 1) Vehicle Assignment Gap

**Rank:** CRITICAL  
**Current Status:** Missing. `/app/vehicles` is a static shell with hardcoded rows; no create/edit/assign vehicle workflow was found.  
**Blocker:** No exposed vehicle workflow exists in the frontend or backend. The model exists, but there is no operational API path to create, edit, or assign vehicles.  
**Impact on Operations:** Dispatch cannot manage actual fleet assets. Trips can be scheduled and assigned to drivers, but the business cannot reliably attach trips to physical vehicles, which breaks real-world fleet coordination and capacity management.  
**Exact Files Involved:**
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
  
**Exact APIs Involved:**
- None found for vehicle create/edit/assign
- Existing fleet shell is rendered client-side only
  
**Exact Database Tables Involved:**
- `health_isf_vehicles`
- `health_isf_drivers`
- `health_isf_rides`
- `health_isf_dispatch_assignments`
  
**Estimated Implementation Effort:** Medium to High  
**Reasoning:** The database model already exists, which reduces schema work, but the platform lacks route handlers, service methods, and UI bindings for the full vehicle workflow.

---

### 2) Billing / Invoice Generation Gap

**Rank:** CRITICAL  
**Current Status:** Partial. Payment tracking exists, but invoice generation and claims workflows are missing. `/app/billing` is hardcoded and non-operational as a revenue workflow.  
**Blocker:** No invoice-generation workflow, no claims workflow, and no operational billing UI.  
**Impact on Operations:** Revenue cannot be formally captured into invoices and claims, so the platform cannot close the loop from completed trip to billable event to collected revenue. This is the primary monetization gap.  
**Exact Files Involved:**
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
  
**Exact APIs Involved:**
- `POST /api/health-isf/payments/intents`
- `POST /api/health-isf/payments/capture`
- `POST /api/health-isf/payments/settle`
- `GET /api/health-isf/payments/rides/{ride_id}`
- No invoice API found
- No claims API found
  
**Exact Database Tables Involved:**
- `health_isf_payment_transactions`
- `health_isf_settlement_ledger`
- `health_isf_payouts`
- `health_isf_rides`
  
**Estimated Implementation Effort:** Medium  
**Reasoning:** Core payment ledgering exists, so this is less expensive than a new domain model, but the missing invoice/claims layer is still a substantial operational gap.

---

### 3) Rider Edit / Search Gap

**Rank:** HIGH  
**Current Status:** Partial. Rider workspace exists and rider/customer ride requests can be created and viewed, but there is no dedicated rider profile edit workflow and search is indirect.  
**Blocker:** No rider directory/profile table and no dedicated rider CRUD API. Search is phone-based workspace lookup and dispatch queue filtering, not a true rider management surface.  
**Impact on Operations:** Customer service and dispatch operations cannot reliably maintain or search a rider master record. This slows support, rebooking, and operational continuity.  
**Exact Files Involved:**
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
  
**Exact APIs Involved:**
- `POST /api/health-isf/customer-requests`
- `GET /api/health-isf/customers/workspace/history`
- `GET /api/health-isf/customers/workspace/active`
- `GET /api/health-isf/customers/workspace/live-tracking`
- `GET /api/health-isf/dispatcher/queues?search_query=...`
  
**Exact Database Tables Involved:**
- `health_isf_customer_ride_requests`
- `health_isf_rides`
- `health_isf_ride_status_history`
- `health_isf_dispatch_logs`
- `health_isf_realtime_events`
  
**Estimated Implementation Effort:** Medium  
**Reasoning:** The ride/request backbone already exists, but rider identity management is not modeled as a first-class operational object.

---

### 4) Driver Creation Gap

**Rank:** HIGH  
**Current Status:** Partial. Driver onboarding exists through driver applications, but direct driver creation was not found.  
**Blocker:** No direct create-driver endpoint was found.  
**Impact on Operations:** The platform can onboard applicants, but it does not expose a clear operational path to create active driver records as a business workflow.  
**Exact Files Involved:**
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
  
**Exact APIs Involved:**
- `POST /api/health-isf/driver-applications`
- `PATCH /api/health-isf/driver-applications/{application_id}/status`
- No direct `POST /api/health-isf/drivers` found
  
**Exact Database Tables Involved:**
- `health_isf_driver_applications`
- `health_isf_drivers`
- `health_isf_driver_sessions`
  
**Estimated Implementation Effort:** Medium  
**Reasoning:** The application pipeline exists, but conversion from applicant to operational driver is not surfaced as a distinct workflow.

---

### 5) Vehicle Create/Edit Gap

**Rank:** HIGH  
**Current Status:** Missing. Vehicle model exists, but no operational CRUD workflow was found.  
**Blocker:** No create/edit API or frontend form for vehicles.  
**Impact on Operations:** Fleet inventory cannot be maintained through the platform, so vehicle state remains a static concept rather than a managed business asset.  
**Exact Files Involved:**
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
  
**Exact APIs Involved:**
- None found
  
**Exact Database Tables Involved:**
- `health_isf_vehicles`
  
**Estimated Implementation Effort:** Medium  
**Reasoning:** Schema exists, but the application layer is absent.

---

### 6) Billing Claims Gap

**Rank:** HIGH  
**Current Status:** Missing. Payment tracking exists, but claims workflows do not.  
**Blocker:** No claims table or claims API was found.  
**Impact on Operations:** The platform can track payment transactions, but cannot manage insurer or payer claim workflows, which limits reimbursement and revenue capture.  
**Exact Files Involved:**
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
  
**Exact APIs Involved:**
- Payment APIs exist, but no claims API found
  
**Exact Database Tables Involved:**
- `health_isf_payment_transactions`
- `health_isf_settlement_ledger`
- `health_isf_payouts`
  
**Estimated Implementation Effort:** Medium to High  
**Reasoning:** A billing ledger exists, but claims management would still require new workflow surfaces and data structures.

---

### 7) Rider Profile Edit Gap

**Rank:** MEDIUM  
**Current Status:** Missing. Only ride/request state is editable.  
**Blocker:** No dedicated rider profile update workflow or table was found.  
**Impact on Operations:** Support staff cannot maintain a stable rider master record for contact, preferences, or rebooking continuity.  
**Exact Files Involved:**
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
  
**Exact APIs Involved:**
- `PATCH /api/health-isf/customer-requests/{request_id}/status`
- Request and workspace lookup endpoints only
  
**Exact Database Tables Involved:**
- `health_isf_customer_ride_requests`
- `health_isf_rides`
  
**Estimated Implementation Effort:** Medium  
**Reasoning:** The system has request-state mutation but not rider identity management.

---

### 8) Dispatch Shell Dependency Gap

**Rank:** MEDIUM  
**Current Status:** Partial. Dispatch is operational, but the unauthenticated shell falls back to demo data when token hydration is absent.  
**Blocker:** The frontend gate requires token/session hydration before loading live ops data.  
**Impact on Operations:** Users without a valid session see synthetic behavior, which can obscure operational truth and hinder real-world usage if session persistence fails.  
**Exact Files Involved:**
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
- [backend/app/auth.py](backend/app/auth.py)
- [backend/app/core/nova/operational_hydration_router.py](backend/app/core/nova/operational_hydration_router.py)
  
**Exact APIs Involved:**
- `GET /api/ops/workspace/activation`
- `POST /api/ops/workspace/action`
- `GET /api/auth/me`
  
**Exact Database Tables Involved:**
- `platform_users`
- `platform_refresh_tokens`
- `platform_operations_tasks`
- `platform_operations_assignment_events`
  
**Estimated Implementation Effort:** Low to Medium  
**Reasoning:** The backend is present; the issue is operational session readiness and shell hydration behavior.

---

### 9) Nova Recommendation Dependency Gap

**Rank:** LOW  
**Current Status:** Operational. Recommendations exist and are live, but depend on authenticated workspace hydration.  
**Blocker:** None material.  
**Impact on Operations:** Low direct impact on the revenue chain compared with trip, fleet, or billing gaps.  
**Exact Files Involved:**
- [backend/app/core/nova/operational_hydration_router.py](backend/app/core/nova/operational_hydration_router.py)
- [backend/app/core/nova/compliance_router.py](backend/app/core/nova/compliance_router.py)
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
  
**Exact APIs Involved:**
- `GET /api/ops/recommendations`
- `GET /api/ops/workspace/activation`
  
**Exact Database Tables Involved:**
- `platform_operations_optimization_recommendations`
- `platform_operations_governance_trends`
- `platform_operations_governance_drift_events`
  
**Estimated Implementation Effort:** Low  
**Reasoning:** This is not a blocking business gap; it is an advisory layer.

---

## Shortest Path Recommendation

If the goal is to turn Amicor Health ISF into a real transportation business as quickly as possible, the order should be:

1. Vehicle assignment workflow
2. Billing invoice generation
3. Claims workflow
4. Rider profile management/search
5. Direct driver creation

**Why this order:**
- Vehicle assignment closes the operational asset gap in the trip chain.
- Invoice generation closes the monetization gap.
- Claims management closes reimbursement and payer workflow.
- Rider and driver master-data gaps improve repeatable scaling.

---

## Final Verdict

The platform already has the backbone for riders, trips, drivers, dispatch, and payment tracking. The fastest path to a real transportation company is to close the missing fleet and billing links first, with vehicle assignment as the highest-value operational gap and invoice generation as the highest-value revenue gap.
