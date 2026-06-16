# MVP Architecture Outline

This outline defines the initial system architecture for Amicor Health ISF inside the Amicor XS ecosystem.

## 1. Authentication

- Email/password and secure token-based session model
- Password reset and account lockout basics
- MFA-ready design for future hardening

## 2. Role-Based Access

- Roles: `admin`, `provider`, `partner_staff`, `dispatcher`, `driver`
- Route-level and action-level authorization
- Role-scoped data visibility

## 3. Provider Requests

- Structured transportation request creation
- Validation for timing, location, and serviceability
- Request lifecycle states and audit trail

## 4. Driver Assignments

- Assignment queue with manual + rules-assisted selection
- Acceptance, reassignment, and cancellation support
- Exception codes for operational edge cases

## 5. Ride Tracking

- Status-based ride lifecycle tracking
- Timestamped events for pickup/transit/dropoff
- Basic map/location abstraction for future integrations

## 6. Notifications

- Event-driven notifications by role and channel
- Core channels: in-app, SMS/email adapter-ready
- Retry and delivery status tracking

## 7. Admin Dashboard

- Live request and assignment visibility
- Exception and SLA watchlist
- Driver availability and operational controls

## 8. Payout Tracking

- Completion-linked payout records
- Manual dispute resolution workflow
- Weekly settlement and reconciliation views

## 9. Reporting

- Core KPIs: request volume, assignment time, completion rate, cancellations
- Partner-level and time-window reporting
- Grant and impact narrative support datasets

## Cross-Cutting Principles

- API-first module boundaries
- Event logging and auditability
- Configurable workflows for regional expansion
- Clear extension points for AI dispatch and analytics
