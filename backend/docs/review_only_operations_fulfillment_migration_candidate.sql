-- REVIEW CANDIDATE ONLY. Do not execute against production until explicit
-- migration review, isolated rehearsal, verified backup/restore, and owner approval.
-- No automatic application. Existing roles, privileges and records are untouched.
-- Seven new tables; fail atomically if any already exists.
-- Execute only via psql with ON_ERROR_STOP=1 and reviewed target.
-- Source blobs:
-- backend/migrations/review_only_operations_package_task_reservations_staging.sql 748d38fec7b8ab9e5c167c1af436a99ac567d410
-- backend/migrations/review_only_operations_subscription_scope_approvals_staging.sql af311837962992af523cda109a6bf0e9b28b5bae
-- backend/migrations/review_only_operations_subscription_csv_bindings_staging.sql 7adda95a5b62eb23b3b8850d3dbdbf798125462e
-- backend/migrations/sql/20261109_operations_customer_csv_jobs_postgres.sql 4965b507c627c2b306e9544ec44247a029eef260
-- backend/staging_migrations/operations_customer_delivery_grants.sql 96f2070936aeb3848097a26782712d156e18e004
-- backend/staging_migrations/operations_starter_payment_bindings.sql 1af74b86ee7194f1afcb2b0d64b61360a976e1ef
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = public, pg_catalog;
DO $guard$
BEGIN
    IF current_database() <> 'amicor' THEN
        RAISE EXCEPTION 'Unexpected database name; stop for review';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
       WHERE n.nspname='public' AND c.relname IN (
        'nova_operations_package_task_reservations',
        'nova_operations_subscription_task_scope_approvals',
        'nova_operations_subscription_scope_approval_events',
        'nova_operations_subscription_csv_bindings',
        'nova_operations_customer_csv_jobs',
        'nova_operations_customer_delivery_grants',
        'nova_operations_starter_payment_bindings')) THEN
        RAISE EXCEPTION 'Existing fulfillment relation found; stop for schema review';
    END IF;
END $guard$;
-- Derived from backend/migrations/review_only_operations_package_task_reservations_staging.sql
CREATE TABLE nova_operations_package_task_reservations (
    id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(128) NOT NULL,
    plan VARCHAR(32) NOT NULL,
    entitlement_id VARCHAR(128) NOT NULL,
    period_key VARCHAR(64) NOT NULL,
    request_key VARCHAR(128) NOT NULL,
    task_fingerprint VARCHAR(64) NOT NULL,
    reserved_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_nova_operations_entitlement_task
        UNIQUE (customer_id, plan, entitlement_id, period_key, request_key),
    CONSTRAINT ck_nova_operations_reservation_plan
        CHECK (plan IN ('starter_49', 'launch_99', 'business_299')),
    CONSTRAINT ck_nova_operations_reservation_fingerprint
        CHECK (task_fingerprint ~ '^[0-9a-f]{64}$')
);
CREATE INDEX ix_nova_ops_task_scope
    ON nova_operations_package_task_reservations
    (customer_id, plan, entitlement_id, period_key);

-- Derived from backend/migrations/review_only_operations_subscription_scope_approvals_staging.sql
CREATE TABLE nova_operations_subscription_task_scope_approvals (
    approval_id VARCHAR(64) PRIMARY KEY,
    organization_id VARCHAR(36) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    engagement_id VARCHAR(32) NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    lead_id VARCHAR(36) NOT NULL,
    task_fingerprint VARCHAR(64) NOT NULL,
    decision VARCHAR(16) NOT NULL CHECK (decision IN ('APPROVED','REJECTED','REVOKED')),
    decided_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_nova_ops_subscription_scope_decision
      UNIQUE (organization_id, owner_user_id, task_id, lead_id, task_fingerprint),
    CONSTRAINT ck_nova_ops_subscription_approval_fingerprint
      CHECK (task_fingerprint ~ '^[0-9a-f]{64}$')
);
CREATE INDEX ix_nova_ops_subscription_approval_scope
  ON nova_operations_subscription_task_scope_approvals
  (organization_id, owner_user_id, engagement_id, task_id, lead_id);
CREATE TABLE nova_operations_subscription_scope_approval_events (
    event_id VARCHAR(64) PRIMARY KEY,
    organization_id VARCHAR(36) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    engagement_id VARCHAR(32) NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    lead_id VARCHAR(36) NOT NULL,
    task_fingerprint VARCHAR(64) NOT NULL CHECK (task_fingerprint ~ '^[0-9a-f]{64}$'),
    decision VARCHAR(16) NOT NULL CHECK (decision IN ('APPROVED','REJECTED','REVOKED')),
    decided_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_nova_ops_approval_events_scope
 ON nova_operations_subscription_scope_approval_events
 (organization_id, owner_user_id, task_id, lead_id, decided_at);

-- Derived from backend/migrations/review_only_operations_subscription_csv_bindings_staging.sql
CREATE TABLE nova_operations_subscription_csv_bindings (
    reservation_id VARCHAR(64) PRIMARY KEY REFERENCES nova_operations_package_task_reservations(id) ON DELETE RESTRICT,
    organization_id VARCHAR(36) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    engagement_id VARCHAR(32) NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    lead_id VARCHAR(36) NOT NULL,
    customer_id VARCHAR(128) NOT NULL,
    subscription_id VARCHAR(128) NOT NULL,
    plan VARCHAR(32) NOT NULL CHECK (plan IN ('launch_99', 'business_299')),
    period_key VARCHAR(64) NOT NULL,
    input_sha256 VARCHAR(64) NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_nova_ops_subscription_csv_task UNIQUE
        (organization_id, owner_user_id, engagement_id, task_id)
);

-- Derived from backend/migrations/sql/20261109_operations_customer_csv_jobs_postgres.sql
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
    status VARCHAR(32) NOT NULL
        CHECK (status IN ('PROCESSING', 'FAILED', 'AWAITING_REVIEW',
                         'APPROVED_FOR_DOWNLOAD', 'REJECTED')),
    reviewer_user_id VARCHAR(36),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_nova_customer_csv_request
        UNIQUE (organization_id, owner_user_id, request_key)
);
CREATE INDEX ix_nova_customer_csv_owned
    ON nova_operations_customer_csv_jobs
    (organization_id, owner_user_id, engagement_id, task_id, updated_at);

-- Derived from backend/staging_migrations/operations_customer_delivery_grants.sql
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
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX ix_nova_operations_delivery_recipient
    ON nova_operations_customer_delivery_grants
    (recipient_user_id, recipient_organization_id, expires_at);

-- Derived from backend/staging_migrations/operations_starter_payment_bindings.sql
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
COMMIT;
-- No GRANT, DROP, data backfill, sales flag or startup migration.
-- Rollback: disable feature routes; retain all evidence. Never drop populated tables.
