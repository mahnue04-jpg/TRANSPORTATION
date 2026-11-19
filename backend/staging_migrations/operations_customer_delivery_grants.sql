-- Review-only Nova Operations customer delivery grants schema.
-- DO NOT apply automatically. Requires separately approved isolated PostgreSQL
-- staging migration, backups, retention policy and restricted private storage.
-- Customer account IDs must refer to verified platform identities.
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
