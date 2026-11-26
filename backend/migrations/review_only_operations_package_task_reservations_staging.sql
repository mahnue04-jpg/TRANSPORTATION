-- AMICOR Nova Operations Agent — staging-only reviewed migration CANDIDATE.
-- DO NOT run on production or against existing customer databases.
-- Preconditions: target is the isolated staging PostgreSQL database;
-- operator has verified backup/restore and recorded the exact connection target.
-- No application automatically runs this migration.
BEGIN;
CREATE TABLE IF NOT EXISTS nova_operations_package_task_reservations (
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
CREATE INDEX IF NOT EXISTS ix_nova_ops_task_scope
    ON nova_operations_package_task_reservations
    (customer_id, plan, entitlement_id, period_key);
COMMIT;
-- Verification (read-only):
-- SELECT COUNT(*) FROM nova_operations_package_task_reservations;
-- SELECT conname FROM pg_constraint
--   WHERE conrelid = 'nova_operations_package_task_reservations'::regclass;
-- Rollback is intentionally NOT automated: require documented staging review
-- of any reservations before DROP TABLE.
