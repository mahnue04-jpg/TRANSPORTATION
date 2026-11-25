-- Review-only isolated staging migration. Never auto-apply or run on production.
-- Requires reviewed package reservations and approval schemas first.
BEGIN;
CREATE TABLE IF NOT EXISTS nova_operations_subscription_csv_bindings (
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
COMMIT;
-- Verify schema and constraints before enabling any staging caller.
-- No automatic rollback: preserve reservation and approval evidence.
