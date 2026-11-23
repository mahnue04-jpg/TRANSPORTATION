# Starter $49 payment-to-task binding — migration review (NOT executed)

Status: **proposal only**, isolated draft PR #577. No migration is registered in Alembic or applied to any database.

## Preconditions
- Obtain explicit owner authorization for a staged migration, including target DB and backup.
- Validate a recoverable backup, capture current Alembic heads, and select the correct parent revision. Do not guess a `down_revision` in a repository with possible multiple heads.
- Verify `marketing_website_leads.starter_paid_session_id` exists from PR #576 and that signed Stripe webhook integration tests pass.
- Do not enable `NOVA_OPERATIONS_STARTER_BINDING_ENABLED` until the full release and private delivery system pass.

## Proposed PostgreSQL DDL (for review, not execution)

```sql
CREATE TABLE nova_operations_starter_payment_bindings (
    lead_id VARCHAR(36) PRIMARY KEY,
    organization_id VARCHAR(36) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    engagement_id VARCHAR(32) NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    stripe_checkout_session_id VARCHAR(128) NOT NULL UNIQUE,
    CONSTRAINT uq_nova_operations_starter_paid_task
        UNIQUE (organization_id, engagement_id, task_id)
);
```

Before release, reconcile this DDL with the reviewed SQLAlchemy `starter_bindings` table exactly. Access must be server-side only; do not expose direct table insert/update permissions to customers. Database uniqueness is the final safeguard against concurrent duplicate funding.

## Dry-run verification checklist
1. Run on a disposable PostgreSQL database with synthetic checkout IDs and task IDs only.
2. Confirm a successful insert, exact retry without duplicate creation, and duplicate-key rejection for a second task or second payment on the same task.
3. Confirm cross-organization and cross-owner mismatches fail via the application binding guard.
4. Simulate transaction rollback, concurrent writes and interrupted requests.
5. Verify `require_paid_starter` rejects unverified leads and mismatched `starter_paid_session_id`.
6. Demonstrate backup restore, inspect table contents, and capture test logs.
7. Leave all payment, task processing and customer delivery feature flags **false**.

## Rollback proposal (review only)

```sql
DROP TABLE nova_operations_starter_payment_bindings;
```

**Danger:** Dropping the table irreversibly destroys paid-task associations unless restored from the approved backup. Never use this rollback with real orders or without an owner-authorized recovery plan.

## Open questions before a production migration
- Whether the table should have additional foreign keys or immutable event identifiers after the identity model is finalized.
- Refund/chargeback revocation design; a valid historical paid session is not sufficient proof of current entitlement after refund.
- Exact owner task authorization and tenant boundaries.
- Alembic migration graph parent revision and staged verification evidence.
