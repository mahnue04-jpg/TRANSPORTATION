-- REVIEW ONLY. Apply solely to an isolated synthetic staging PostgreSQL database
-- after explicit target, backup, rollback and approval verification.
-- No auto-migration, no production or customer data.
BEGIN;
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
COMMIT;
-- NEVER infer consent/approval by populating this table from existing task status.
-- Approval write path and revocation audit must be implemented and separately tested.
