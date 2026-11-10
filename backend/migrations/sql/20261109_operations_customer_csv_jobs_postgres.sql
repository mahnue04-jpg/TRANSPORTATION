-- Nova Operations customer CSV durable job metadata, proposed migration.
-- Apply ONLY after isolated staging review. DO NOT auto-run at startup.
-- Artifact CSV bytes stay in private encrypted S3-compatible storage.
CREATE TABLE IF NOT EXISTS nova_operations_customer_csv_jobs (
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
CREATE INDEX IF NOT EXISTS ix_nova_customer_csv_owned
    ON nova_operations_customer_csv_jobs
    (organization_id, owner_user_id, engagement_id, task_id, updated_at);

-- No DROP is part of a production rollback. Disable the feature flag to
-- stop new operations; preserve records for forensic/recovery review.
