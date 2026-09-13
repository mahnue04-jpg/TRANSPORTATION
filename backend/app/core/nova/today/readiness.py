"""Nova V2 beta readiness checklist. Factual statuses only. No production deploy."""
from __future__ import annotations

from typing import Literal

CheckStatus = Literal["PASS", "BLOCKED", "NOT TESTED"]


def beta_readiness_checklist(*, signed_in_ui: CheckStatus = "NOT TESTED") -> list[dict[str, str]]:
    return [
        {"key": "tenant_isolation", "label": "Tenant isolation", "status": "PASS"},
        {"key": "connector_isolation", "label": "Connector isolation", "status": "PASS"},
        {"key": "auth", "label": "Auth-gated Today APIs", "status": "PASS"},
        {"key": "approval_controls", "label": "Approval controls", "status": "PASS"},
        {"key": "prohibited_actions", "label": "Prohibited actions blocked", "status": "PASS"},
        {"key": "audit_history", "label": "Audit / history", "status": "PASS"},
        {"key": "communications_read_path", "label": "Communications read path", "status": "PASS"},
        {"key": "source_health", "label": "Source health", "status": "PASS"},
        {"key": "connector_freshness", "label": "Connector freshness", "status": "PASS"},
        {"key": "draft_verification", "label": "Draft verification", "status": "PASS"},
        {"key": "task_verification", "label": "Task verification", "status": "PASS"},
        {"key": "ask_nova_context", "label": "Ask Nova context", "status": "PASS"},
        {"key": "empty_states", "label": "Empty states", "status": "PASS"},
        {"key": "degraded_states", "label": "Degraded / stale / unavailable states", "status": "PASS"},
        {"key": "no_secret_leakage", "label": "No secret leakage in Today payloads", "status": "PASS"},
        {"key": "no_new_paid_service", "label": "No new paid service dependency", "status": "PASS"},
        {"key": "no_production_deployment", "label": "No production deployment", "status": "PASS"},
        {"key": "signed_in_owner_ui", "label": "Signed-in owner UI validation", "status": signed_in_ui},
    ]
