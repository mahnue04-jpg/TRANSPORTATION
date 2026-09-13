"""Phase 2B allowlists. Persist-only; does not widen Phase 1 action permissions."""
from __future__ import annotations

from app.core.nova.autonomy.policy import LOW_ACTIONS, MEDIUM_ACTIONS, normalize_action_type

WORKFLOW_TYPES = frozenset(
    {
        "research_draft_task",
        "gov_opportunity_response",
        "customer_inquiry_response",
        "business_lead_outreach",
        "ops_issue_recommend",
    }
)

INITIATING_MODULES = frozenset(
    {
        "today",
        "communications",
        "business",
        "government",
        "workspace",
        "link",
        "autonomy",
    }
)

# Allowed initiating module + optional declared action per template.
# Actions stay inside Phase 1 LOW/MEDIUM names; none are executed here.
WORKFLOW_TEMPLATES: dict[str, dict[str, frozenset[str]]] = {
    "research_draft_task": {
        "modules": frozenset({"today", "workspace", "autonomy", "business", "government"}),
        "actions": frozenset({"recheck_source", "create_draft", "create_task"}),
    },
    "gov_opportunity_response": {
        "modules": frozenset({"government", "today", "autonomy"}),
        "actions": frozenset({"recheck_source", "history", "create_draft", "create_task"}),
    },
    "customer_inquiry_response": {
        "modules": frozenset({"communications", "business", "today", "autonomy"}),
        "actions": frozenset({"recheck_source", "history", "create_draft"}),
    },
    "business_lead_outreach": {
        "modules": frozenset({"business", "today", "autonomy"}),
        "actions": frozenset({"recheck_source", "create_draft", "create_task"}),
    },
    "ops_issue_recommend": {
        "modules": frozenset({"today", "link", "autonomy", "workspace"}),
        "actions": frozenset({"open_link", "history", "recheck_source", "acknowledge", "create_draft"}),
    },
}

ALLOWED_ACTIONS = LOW_ACTIONS | MEDIUM_ACTIONS


def normalize_workflow_type(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_module(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def validate_create(*, workflow_type: str, initiating_module: str, action_type: str | None) -> tuple[str, str, str | None]:
    kind = normalize_workflow_type(workflow_type)
    if kind not in WORKFLOW_TYPES:
        raise ValueError("Unknown workflow_type")
    module = normalize_module(initiating_module)
    template = WORKFLOW_TEMPLATES[kind]
    if module not in INITIATING_MODULES or module not in template["modules"]:
        raise ValueError("Unknown module/action combination")
    action = normalize_action_type(action_type) if action_type else None
    if action:
        if action not in ALLOWED_ACTIONS or action not in template["actions"]:
            raise ValueError("Unknown module/action combination")
    return kind, module, action or None
