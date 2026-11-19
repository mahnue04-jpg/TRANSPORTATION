-- Operations Starter Task binding schema (review-only DDL).
-- DO NOT execute through startup, production deploy, or migration automation.
-- Requires separately approved staging backup/restore and migration execution.
-- This table stores Stripe checkout identifiers, never card or bank details.
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
