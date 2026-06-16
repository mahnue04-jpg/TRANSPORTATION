# Amicor Health ISF MVP Execution Tracker (6-Week)

## Team Owner Map (Pre-Filled)

Use real names beside each role.

- Executive Owner: Founder/CEO (Name: __________________)
- Product Owner: Product Lead (Name: __________________)
- Engineering Owner: Backend Lead (Name: __________________)
- Operations Owner: Ops Lead / Dispatch Lead (Name: __________________)
- Partnerships Owner: Partnerships Lead (Name: __________________)
- Driver Network Owner: Driver Ops Lead (Name: __________________)
- Finance Owner: Finance Lead (Name: __________________)
- Legal Owner: Legal/Compliance Lead (Name: __________________)
- Grants Owner: Grants Lead (Name: __________________)

Constraints locked for MVP:
- Admin-driven operations
- No AI dispatching
- No advanced automation
- No microservices
- Reliability first

Status legend: Not started | In progress | At risk | Blocked | Complete

## 6-Week Phase Plan

| Week | Phase | Outcome | Primary Owner | Status | Go/No-Go Exit Criteria |
|---|---|---|---|---|---|
| Week 1 | Business + legal setup | Pilot scope, agreements, and policies prepared | Founder + Legal + Ops | Not started | Provider agreement draft ready; service area/SLA defined; escalation policy approved |
| Week 2 | Access + intake foundation | Provider/admin/driver access and client intake flow usable | Product + Backend | Not started | Provider can create valid client records with service area validation |
| Week 3 | Ride request + queue | Requests reliably validate and enter queue | Backend + Product | Not started | Request submission and queued state confirmed for valid rides |
| Week 4 | Manual assignment + dispatch | Admin assigns driver and ride reaches in_transit | Ops + Backend | Not started | Assignment, accept/decline, and dispatch state transitions working |
| Week 5 | First completed rides + notifications | End-to-end completed rides with provider updates | Ops + Driver Ops | Not started | At least 3 completed rides logged with completion notifications |
| Week 6 | Billing/payout + stabilization | Weekly invoice and payout cycle closed | Finance + Ops + Founder | Not started | Invoice batch approved/sent and payout batch settled with reconciliation report |

## Critical Path (6-Week)

| Step | Owner | Target Week | Status | Evidence |
|---|---|---|---|---|
| Provider onboarded and active | Partnerships | Week 1 | Not started | Signed agreement + active account |
| Driver onboarded and active | Driver Ops | Week 2 | Not started | Verification checklist complete |
| Client record created | Provider Ops | Week 3 | Not started | Client profile exists |
| Ride request queued | Provider Ops | Week 3 | Not started | Request ID in queued state |
| Driver assigned and accepted | Dispatch Admin + Driver | Week 4 | Not started | Assignment + acceptance timestamps |
| Ride completed | Driver + Dispatch Admin | Week 5 | Not started | completed state with timestamps |
| Completion notification sent | Ops/System | Week 5 | Not started | Notification log |
| Billing record and payout record created | Finance/Ops | Week 6 | Not started | Audit records in dashboard/export |

## Business/Legal Gate Checklist

| Milestone | Owner | Target Week | Status |
|---|---|---|---|
| Provider service agreement finalized | Legal + Founder | Week 1 | Not started |
| Pilot provider agreement executed | Founder + Partnerships | Week 1 | Not started |
| Driver contractor terms finalized | Legal + Driver Ops | Week 1 | Not started |
| Safety incident policy approved | Ops | Week 1 | Not started |
| Cancellation/no-show policy approved | Ops + Finance | Week 1 | Not started |
| Billing dispute policy approved | Finance + Legal | Week 2 | Not started |
| Invoice/payout approval matrix assigned | Founder + Finance | Week 2 | Not started |

## Grant Readiness Checklist

| Item | Owner | Target Week | Status |
|---|---|---|---|
| Grant calendar + ownership matrix | Grants | Week 1 | Not started |
| Narrative package (mission/problem/impact) | Founder + Grants | Week 2 | Not started |
| KPI definition set (completion, exceptions, attendance support) | Ops + Product | Week 2 | Not started |
| Monthly grant summary template | Grants + Ops | Week 3 | Not started |
| Evidence folder (letters, exports, screenshots) | Partnerships + Ops | Week 4 | Not started |

## Deployment Milestones (6-Week)

| Milestone | Owner | Target Week | Status | Criteria |
|---|---|---|---|---|
| Local baseline stable | Backend | Week 2 | Not started | Health checks pass and core flows run locally |
| Staging pilot ready | Backend + Ops | Week 4 | Not started | End-to-end staging ride succeeds |
| Production pilot launch | Founder + Ops | Week 5 | Not started | On-call and escalation staffing confirmed |
| Post-launch stabilization | Ops + Finance | Week 6 | Not started | First weekly billing/payout cycle completed |

## Weekly Operating Rhythm

- Monday: status and blocker update
- Wednesday: dependency and risk review
- Friday: go/no-go gate decision

Rule: if exit criteria are not evidenced, do not advance phases.
