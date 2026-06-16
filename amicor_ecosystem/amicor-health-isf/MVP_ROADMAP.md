# Amicor Health ISF MVP Roadmap

## 1. Mission
Amicor Health ISF exists to close healthcare access gaps by coordinating reliable transportation for underserved and rural communities, with an initial focus on behavioral health continuity.

MVP success means one simple outcome: providers can reliably request rides, vetted drivers complete them, and operations can track quality, billing, and payouts with auditability.

## 2. Revenue model
Primary revenue streams for MVP:
- Provider service agreements for completed rides.
- Program-based pilot contracts with healthcare and community partners.
- Grant funding for rural access, behavioral health continuity, and transportation barrier reduction.

MVP financial model:
- Weekly provider invoicing (batch).
- Weekly driver payout settlement (batch).
- Manual admin approval before invoice and payout release.

## 3. Core operational workflows
The MVP operating system is seven workflows:
1. Client intake (provider-managed rider record creation).
2. Ride request (provider submits appointment transport request).
3. Driver assignment (admin-driven, manual assignment from eligible driver pool).
4. Dispatch (driver executes pickup and dropoff with state updates).
5. Provider communication (status notifications and exception alerts).
6. Billing and payout (weekly invoice and settlement cycles).
7. Admin dashboard operations (queue oversight, exceptions, reporting, approvals).

Ride lifecycle for operational control:
- requested
- queued
- assigned
- en_route_pickup
- in_transit
- completed
- cancelled
- exception

## 4. MVP boundaries
Operating boundaries for this MVP:
- Admin-driven dispatch and exception resolution.
- Single deployable application (no microservices split).
- Workflow reliability over automation depth.
- Weekly finance cycles over real-time settlement.
- Core reporting for operations and grant visibility only.

Execution boundaries:
- Build only what is needed to run rides reliably end-to-end.
- Prefer manual controls where automation would increase risk.
- Keep integrations minimal and replaceable.

## 5. What is intentionally excluded from MVP
Explicit non-goals:
- AI dispatching or AI optimization in production assignment decisions.
- Advanced automation (auto-dispute adjudication, auto-reassignment logic, fully automated payouts).
- Enterprise claims processing.
- Real-time GPS dispatch optimization and live map operations.
- Multi-region infrastructure and distributed architecture.
- Microservices decomposition.
- Deep BI/analytics platform and custom reporting engine.

## 6. Phase-by-phase build sequence
Each phase should end with a usable checkpoint and a go/no-go review.

### Phase 0: Business setup and partner readiness
- Select first pilot region and partner cohort.
- Define service hours, SLAs, and escalation policy.
- Confirm provider and driver onboarding requirements.

Exit criteria:
- At least one pilot provider and minimum driver cohort pre-qualified.

### Phase 1: Access and intake foundation
- Role-based access for provider, driver, admin.
- Provider portal basics for client intake.
- Service area and validation checks.

Exit criteria:
- Provider can create and manage valid rider records.

### Phase 2: Ride request intake
- Request submission flow with required fields.
- Validation rules (timing window, service area, rider readiness).
- Request queue creation and provider confirmation.

Exit criteria:
- Valid request consistently enters dispatch queue.

### Phase 3: Admin-driven assignment
- Assignment queue and eligible driver list.
- Manual assign, reassign, and cancel controls.
- Driver acceptance/decline flow with timeout alerts.

Exit criteria:
- Admin can assign a queued request and reach assigned state.

### Phase 4: Dispatch and completion
- Driver status updates from assigned to completed.
- Exception capture and escalation flow.
- Provider status notifications at key milestones.

Exit criteria:
- First successful end-to-end completed ride.

### Phase 5: Billing and payout controls
- Billing record generation on ride completion.
- Weekly provider invoice batch generation and approval.
- Weekly driver payout queue and settlement tracking.

Exit criteria:
- One closed weekly cycle with auditable invoice and payout records.

### Phase 6: Admin operations and reporting hardening
- Admin dashboard views for queue, exceptions, payouts, invoices.
- Weekly exports and grant-aligned summary metrics.
- Reliability hardening for manual fallback operations.

Exit criteria:
- Operations team can run daily workflow without engineering intervention.

## 7. Critical path to first completed ride
Minimum path that must work before pilot launch:
1. Provider onboarded and active.
2. Driver onboarded, vetted, and active.
3. Client record created and validated.
4. Ride request submitted and queued.
5. Admin assigns eligible driver.
6. Driver accepts assignment.
7. Driver executes pickup and dropoff updates.
8. Ride marked completed.
9. Provider receives completion notice.
10. Completion record is auditable in admin dashboard.

Definition of done for first ride:
- Completed ride state reached with timestamps.
- No manual database edits required.
- Exception path remains available if anything fails.

## 8. Required business/legal milestones
Complete these before production pilot rides:

### Partner and service agreements
- Provider service agreement signed.
- SLA and escalation commitments documented.
- Service area boundaries approved.

### Driver compliance and contractor readiness
- Identity verification complete.
- Background checks complete.
- Vehicle and insurance validation complete.
- Independent contractor terms acknowledged.

### Operational and policy controls
- Incident/safety escalation policy approved.
- Rider privacy and data handling policy approved.
- Cancellation and no-show policy approved.
- Dispute handling policy for billing and payouts approved.

### Finance governance
- Invoice approval authority assigned.
- Payout approval authority assigned.
- Weekly reconciliation process documented.

## 9. Grant readiness checklist
Use this checklist before each grant submission cycle:

- Grant calendar and owner matrix maintained.
- Priority themes mapped to current pilot outcomes:
  - rural health access and equity
  - behavioral health continuity
  - transportation barrier reduction
  - community health system innovation
- Reusable narrative package updated:
  - mission and problem statement
  - partner profile and service area
  - operational model and controls
- Metrics package current:
  - request volume
  - completion rate
  - cancellation/exception rate
  - provider participation
  - coverage footprint
- Monthly grant performance summary generated.
- Evidence artifacts ready:
  - partner letters or commitments
  - workflow screenshots/reports
  - operational KPI exports

## 10. Deployment milestones
Deployment should follow reliability gates, not feature count.

### Milestone A: Local operational baseline
- App starts cleanly with documented command.
- Health endpoints pass.
- Core request-assignment-dispatch path testable locally.

### Milestone B: Staging pilot environment
- Environment variables validated.
- Provider, driver, admin test accounts seeded.
- End-to-end test ride executed in staging.

### Milestone C: Pilot production launch
- Daily ops checklist in place.
- On-call and escalation roles assigned.
- Backup snapshot and rollback plan prepared.

### Milestone D: Post-launch stabilization
- First weekly billing and payout cycle completed.
- Exception trends reviewed and controls adjusted.
- Provider feedback loop captured and prioritized.

## 11. Future module expansion strategy
Expand only after Health ISF operations are stable and repeatable.

Expansion rules:
- Keep shared core platform standards (auth, workflow, observability, data patterns).
- Add modules as bounded business domains, not as premature infrastructure splits.
- Preserve single-app architecture until clear scaling thresholds are reached.
- Introduce automation incrementally after operational reliability is proven.

Candidate next modules:
- Partner operations enhancements.
- Advanced scheduling assistance (still human-supervised).
- Financial planning enhancements.
- Grant operations tooling.

Scale trigger for deeper architecture changes:
- Sustained multi-region operations,
- clear independent team ownership,
- and measurable bottlenecks that cannot be solved within current monolith.

Until then: prioritize execution quality, dispatch reliability, and repeatable partner outcomes.
