# AMICOR Nova Operations Agent — approved package scope and staging acceptance

Approval recorded: 2026-11-22 (America/Chicago). **This is scope approval for staging implementation and testing, not authorization for production deployment, live Stripe, paid resources, or real customer processing.**

## Package configuration

| Plan key | Public label | Price | Allowance per billing period | Delivery |
| --- | --- | --- | --- | --- |
| `free_scope` | Free Scope Check | $0 | Qualification/review only, no fulfilled paid job | Owner response |
| `starter_49` | Starter Task | $49 one-time | 1 small scoped task | Owner-approved private file |
| `launch_99` | Launch Operations | $99/month | Up to 3 tasks per subscription month | Owner-reviewed private deliverables |
| `business_299` | Business Operations | $299/month | Up to 10 tasks per subscription month | Owner-reviewed private deliverables and priority support |

Tasks can include CSV/spreadsheet cleanup, basic reports, and permitted administrative workflow support, proportionate to the plan. Priority support is relative triage, **not a guaranteed response time** until separately published. No autonomous financial transactions, regulated advice, sensitive customer datasets, or unreviewed external actions are authorized by this scope decision.

## Billing-period and task definitions (implementation acceptance)

- Starter: one unique paid, verified Stripe checkout binds exactly one approved small task; retries must not consume extra allowance or produce duplicate delivery grants.
- Subscriptions: usage keyed to Stripe subscription ID and current verified billing period; count each accepted, unique scoped task once, not each retry, job execution, or revision. Never reset allowances just because a checkout session was replayed.
- A free quote/scope review is not a paid task; out-of-scope work must be rejected or quoted separately *before* processing.
- At the allowance limit, fail closed and invite an owner-approved upgrade/next-cycle decision; no surprise overages or automatic tier change.
- No charging or provisioning from a return URL alone. Verify signed Stripe webhook, customer, plan, price, subscription status, billing period, and event idempotency.
- Refunds, disputes, failed invoices, canceled subscriptions and expired service periods must stop new paid work under affected entitlement; authorized access to preexisting files is governed by explicit grant expiry/revocation and applicable retention policy.
- Cancellation should be self-service or supported by a documented request path, with clear effective date and no unapproved recurring charge.

## Security and staging checks

- Only test-mode Stripe keys, synthetic `.invalid` accounts, free staging resources. No production data.
- Never leak tokens, keys, PII or private artifacts to client HTML, source control, public logs or links.
- Owner checks scope and approves task execution and each final deliverable.
- Signed-out / wrong customer / revoked recipient cannot fetch private artifacts. Exact intended recipient can; checksum matches expected approved content. Rotate any exposed rehearsal credentials.
- Validate duplicate event delivery, duplicate job request, retries, grant reissue, revocation, file expiry, payment reversal, subscription month boundary, upgrade/downgrade, cancellation, and failed renewal.
- Maintain an immutable or auditable receipt of owner decisions and successful handoffs. Distinguish download offered from customer receipt acknowledgment.

## Customer-facing policy work **not yet approved as final wording**

Before sales release, finalize and separately approve: precise definition of small/medium task and data limits; maximum size and allowed file types; turnaround expectations and revision allowance; availability and support response targets; refund and dispute policy; cancellation/effective-date terms; privacy/retention/deletion policy; exclusions; service agreement; Minnesota and other applicable state tax determination; Stripe Tax/registration decision.

## Release gates

1. Implement allowance enforcement and durable entitlements in staging; pass automated and hosted end-to-end tests for each tier.
2. Verify security, support, notices, data retention, receipts, dispute controls and tax treatment.
3. Review public copy and contract terms with owner.
4. **Separate explicit owner approval** required for live Stripe credentials, production deployment, real customer records, and accepting payments. Live sales remain OFF until then.
