"""Tests for Nova capability execution playbooks."""
from app.core.nova.v3.execution_playbooks import (
    execution_plan_for_matches,
    execution_playbook,
    execution_playbooks,
)


def test_every_capability_has_an_execution_playbook():
    rows = execution_playbooks()
    assert len(rows) == 10
    assert all(row["steps"] for row in rows)
    assert all(row["quality_checks"] for row in rows)
    assert all(row["owner_gates"] for row in rows)


def test_automation_playbook_requires_production_approval():
    row = execution_playbook("ai_workflow_automation")
    assert row is not None
    assert "approve_production_change" in row["owner_gates"]
    assert row["external_submission"] is False
    assert row["financial_execution"] is False


def test_web_software_playbook_requires_merge_and_deploy_approval():
    row = execution_playbook("web_software")
    assert row is not None
    assert "approve_merge" in row["owner_gates"]
    assert "approve_deploy" in row["owner_gates"]


def test_rfp_playbook_keeps_pricing_and_submission_owner_controlled():
    row = execution_playbook("proposal_rfp")
    assert row is not None
    assert "approve_pricing" in row["owner_gates"]
    assert "approve_external_submission" in row["owner_gates"]


def test_execution_plan_uses_top_capability_match():
    plan = execution_plan_for_matches(
        [
            {"capability_id": "data_spreadsheet", "score": 95},
            {"capability_id": "business_research", "score": 75},
        ]
    )
    assert plan["execution_ready"] is True
    assert plan["primary_capability_id"] == "data_spreadsheet"
    assert plan["playbook"]["label"] == "Data & spreadsheet work"
    assert plan["external_submission"] is False
    assert plan["financial_execution"] is False


def test_execution_plan_refuses_empty_matches():
    plan = execution_plan_for_matches([])
    assert plan["execution_ready"] is False
    assert plan["playbook"] is None
