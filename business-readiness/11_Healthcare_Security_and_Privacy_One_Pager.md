# Healthcare Security and Privacy One-Pager

## Purpose
Provide partners and grant reviewers with a concise summary of Amicor's operational security and privacy posture.

## Owner
Security/Compliance Lead (primary), Engineering Lead (technical validation), COO (approval).

## When Used
Partner diligence, security review packets, pilot procurement, grant evidence appendices.

## Draft One-Pager Content

### Security Principles
- Least-privilege access by role
- Tenant-aware isolation of operational data
- Auditability of sensitive operational actions
- Incident detection and escalation procedures

### Access and Identity Controls
- Role-based access controls for admin, dispatcher, driver, provider, and read-only roles
- Token-based authenticated API access
- Tenant-scoped authorization checks on operational routes
- WebSocket subscription authorization controls

### Data Handling Controls
- Minimum necessary operational data use for ride coordination
- Logged status transitions and operational actions
- Controlled exports for partner reporting and grant evidence
- Segregated organizational scope where required

### Monitoring and Audit
- Security and suspicious activity event persistence
- Operational audit logs for key actions
- Exception and incident records maintained for review

### Incident Management
- Escalation policy with severity-based response targets
- Documented notification and corrective-action workflow
- Post-incident review process for critical events

### Operational Reliability Safeguards
- Health endpoints and runtime monitoring
- Dispatch event tracking and replay-safe operations
- Controlled rollout and validation practices

### Partner Assurance Summary
Amicor is designed for controlled healthcare transportation operations with security-minded role controls, auditable workflows, and policy-based escalation.

## Missing Information Required from Amicor
- Formal HIPAA/legal classification stance and legal review statement
- Final breach notification commitments and timelines
- Data retention and deletion schedule
- Third-party vendor/security dependency inventory
- Contact for security questionnaires and reviews
