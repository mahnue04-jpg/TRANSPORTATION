-- PREPARATION ONLY. Do NOT execute on any current database without
-- staging-only owner approval, verified backup, separate least-privilege role
-- and explicit database selection.
-- This migration intentionally never touches the public schema.
BEGIN;
CREATE SCHEMA IF NOT EXISTS nova_ops_checkout_sandbox;
CREATE TABLE IF NOT EXISTS nova_ops_checkout_sandbox.starter_test_orders (
    lead_id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    customer_id VARCHAR(128) NOT NULL,
    plan VARCHAR(32) NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_ops_sandbox_order_session UNIQUE (session_id),
    CONSTRAINT ck_ops_sandbox_order_plan CHECK (plan = 'starter_49'),
    CONSTRAINT ck_ops_sandbox_order_amount CHECK (amount_cents = 4900),
    CONSTRAINT ck_ops_sandbox_order_currency CHECK (currency = 'usd')
);
CREATE TABLE IF NOT EXISTS nova_ops_checkout_sandbox.starter_test_receipts (
    lead_id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    customer_id VARCHAR(128) NOT NULL,
    stripe_event_id VARCHAR(128) NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) NOT NULL,
    payment_status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_ops_sandbox_receipt_session UNIQUE (session_id),
    CONSTRAINT uq_ops_sandbox_receipt_event UNIQUE (stripe_event_id),
    CONSTRAINT ck_ops_sandbox_amount CHECK (amount_cents = 4900),
    CONSTRAINT ck_ops_sandbox_currency CHECK (currency = 'usd'),
    CONSTRAINT ck_ops_sandbox_paid CHECK (payment_status = 'paid')
);
COMMIT;
-- No grants are applied. Provision a dedicated role with only schema USAGE
-- and table SELECT/INSERT. Do not grant CREATE, UPDATE, DELETE, TRUNCATE,
-- public schema permissions or owner-level DB privileges.
