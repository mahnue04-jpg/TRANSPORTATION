# Starter Task private-delivery PostgreSQL schema — review only

**Not applied or registered as an Alembic migration.** This proposal is for code review and a future disposable PostgreSQL rehearsal. No production database or customer storage has been changed.

## Dependencies and order

1. Signed Stripe payment-verification change in draft PR #576 (including `starter_paid_session_id`).
2. One-payment-to-one-task binding table proposal in draft PR #577.
3. The following private CSV jobs and delivery grants, only after a reviewed Alembic parent revision is chosen, target database is identified, and an independently verified backup is available.
4. Owner-assignment and customer-delivery APIs **must remain unregistered** until full test-mode acceptance.

## Proposed DDL (PostgreSQL, review only — DO NOT RUN against production)

```sql
CREATE TABLE nova_operations_customer_csv_jobs (
    id VARCHAR(36) PRIMARY KEY,
    organization_id VARCHAR(36) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    engagement_id VARCHAR(32) NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    request_key VARCHAR(120) NOT NULL,
    input_sha256 VARCHAR(64) NOT NULL,
    output_sha256 VARCHAR(64),
    output_ref VARCHAR(512),
    status VARCHAR(32) NOT NULL,
    reviewer_user_id VARCHAR(36),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_nova_customer_csv_request
        UNIQUE (organization_id, owner_user_id, request_key)
);

CREATE TABLE nova_operations_customer_delivery_grants (
    job_id VARCHAR(36) PRIMARY KEY,
    organization_id VARCHAR(36) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    engagement_id VARCHAR(32) NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    lead_id VARCHAR(36) NOT NULL,
    recipient_user_id VARCHAR(36) NOT NULL,
    recipient_organization_id VARCHAR(36) NOT NULL,
    output_sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE
);
```

These definitions reproduce the module-local SQLAlchemy tables for draft review; they are **not** a complete production-hardening schema. Evaluate whether foreign keys, indexes for recipient + expiry, check constraints for job status, and immutable payment event identifiers are required before authoring a real Alembic revision.

## Acceptance checks on disposable PostgreSQL

- Create schema, introspect columns/constraints and compare exactly with module-local SQLAlchemy metadata.
- Insert synthetic CSV job; duplicate `organization_id/owner_user_id/request_key` must fail, but other owner/tenant keys must remain isolated.
- Simulate owner approval, a verified account-bound grant, expiration, a revoked grant, mismatched recipient and checksum, and repeated requests.
- Verify private bucket read/write/delete only with dedicated staging credentials. No public URLs, public bucket permissions, or unencrypted downloads.
- Verify rollback and restored backup on disposable data. Do not drop tables holding paid-order associations.
- Test interruptions between private-object upload and metadata commit; reconcile orphans before release.
- Verify indexes/performance, concurrent inserts, recovery after failed writes, and expiry enforcement.
- Confirm owner review, issuance and revocation endpoints require authenticated, authorized accounts and explicit action headers.
- Require live entitlements to reflect refunds/chargebacks, not only historical `paid` sessions.

## Release boundaries

All relevant feature flags must remain **false**. This proposal creates no actual tables and cannot authorize live checkout, production migrations, account provisioning, paid infrastructure or real customer work.
