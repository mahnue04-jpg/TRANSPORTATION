# Amicor Health ISF MVP Execution Tracker (8-Week)

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

## 8-Week Phase Plan

| Weeks | Phase | Outcome | Primary Owner | Status | Go/No-Go Exit Criteria |
|---|---|---|---|---|---|
| Weeks 1-2 | Business + legal setup | Partner agreements, policies, pilot scope complete | Founder + Legal + Partnerships | Not started | Provider agreement executed; SLA/escalation/cancellation policies approved |
| Week 3 | Access + intake foundation | Role access and client intake operating | Product + Backend | Not started | Provider can create valid client records with service area validation |
| Week 4 | Ride request + queue | Requests validated and queued reliably | Backend + Product | Not started | Valid request enters queued state with confirmations |
| Week 5 | Manual assignment controls | Admin assignment, reassign, and escalation working | Ops + Backend | Not started | Assignment flow stable with accept/decline and timeout escalation |
| Week 6 | Dispatch + first completed rides | End-to-end rides complete with provider notifications | Ops + Driver Ops | Not started | At least 5 completed rides with auditable state transitions |
| Week 7 | Billing/payout cycle | Invoice and payout weekly cycle operational | Finance + Ops | Not started | Invoice batch approved/sent and payout batch settled |
| Week 8 | Stabilization + reporting + grant packaging | Repeatable operations and grant-ready evidence | Ops + Founder + Grants | Not started | Weekly operating cadence stable and KPI/report pack generated |

## Critical Path (8-Week)

| Step | Owner | Target Week | Status | Evidence |
|---|---|---|---|---|
| Provider onboarded and active | Partnerships | Week 2 | Not started | Signed agreement + active account |
| Driver onboarded and active | Driver Ops | Week 3 | Not started | Driver verification checklist complete |
| Client record created | Provider Ops | Week 4 | Not started | Client profile exists |
| Ride request queued | Provider Ops | Week 4 | Not started | Request ID in queued state |
| Driver assigned and accepted | Dispatch Admin + Driver | Week 5 | Not started | Assignment and acceptance timestamps |
| Ride completed | Driver + Dispatch Admin | Week 6 | Not started | completed state with timestamps |
| Completion notification sent | Ops/System | Week 6 | Not started | Notification log |
| Billing/payout records completed | Finance/Ops | Week 7 | Not started | Reconciliation export |

## Business/Legal Gate Checklist

| Milestone | Owner | Target Week | Status |
|---|---|---|---|
| Provider service agreement finalized | Legal + Founder | Week 1 | Not started |
| Pilot provider agreement executed | Founder + Partnerships | Week 2 | Not started |
| Driver contractor terms finalized | Legal + Driver Ops | Week 2 | Not started |
| Safety incident policy approved | Ops | Week 2 | Not started |
| Cancellation/no-show policy approved | Ops + Finance | Week 2 | Not started |
| Billing dispute policy approved | Finance + Legal | Week 3 | Not started |
| Invoice/payout approval matrix assigned | Founder + Finance | Week 3 | Not started |

## Grant Readiness Checklist

| Item | Owner | Target Week | Status |
|---|---|---|---|
| Grant calendar + ownership matrix | Grants | Week 2 | Not started |
| Narrative package (mission/problem/impact) | Founder + Grants | Week 3 | Not started |
| KPI definition set (completion, exceptions, attendance support) | Ops + Product | Week 4 | Not started |
| Monthly grant summary template | Grants + Ops | Week 5 | Not started |
| Evidence folder (letters, exports, screenshots) | Partnerships + Ops | Week 6 | Not started |
| First grant-ready evidence packet | Grants + Founder | Week 8 | Not started |

## Deployment Milestones (8-Week)

| Milestone | Owner | Target Week | Status | Criteria |
|---|---|---|---|---|
| Local baseline stable | Backend | Week 3 | Not started | Health checks pass and core flows run locally |
| Staging pilot ready | Backend + Ops | Week 5 | Not started | End-to-end staging ride succeeds |
| Production pilot launch | Founder + Ops | Week 6 | Not started | On-call and escalation staffing confirmed |
| Post-launch stabilization | Ops + Finance | Week 8 | Not started | First weekly billing/payout cycle closed and reviewed |

## Weekly Operating Rhythm

- Monday: status and blocker update
- Wednesday: dependency and risk review
- Friday: go/no-go gate decision

Rule: if exit criteria are not evidenced, do not advance phases.
