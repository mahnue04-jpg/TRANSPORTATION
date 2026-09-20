"""Tests for Nova internal work packets."""
from app.core.nova.v3.work_packets import build_work_packet


def test_builds_ready_research_packet():
    packet = build_work_packet(
        {
            "opportunity_title": "B2B competitor research project",
            "company_name": "Example Client",
            "description": "Need competitor research, market research, comparison table and research report.",
            "requirements": "Remote vendor project.",
        }
    )
    assert packet["execution_ready"] is True
    assert packet["primary_capability_id"] == "business_research"
    assert packet["tasks"]
    assert packet["deliverables"]
    assert packet["quality_checks"]
    assert packet["completion_evidence_required"]
    assert packet["external_submission"] is False
    assert packet["financial_execution"] is False


def test_builds_automation_packet_with_test_evidence():
    packet = build_work_packet(
        {
            "opportunity_title": "AI workflow automation vendor",
            "description": "Build AI workflow automation with Zapier and API integration.",
        }
    )
    assert packet["execution_ready"] is True
    assert packet["primary_capability_id"] == "ai_workflow_automation"
    assert "workflow test cases" in packet["completion_evidence_required"]
    assert "approve_production_change" in packet["owner_gates"]
    assert packet["production_deploy"] is False


def test_blocks_human_only_packet():
    packet = build_work_packet(
        {
            "opportunity_title": "On-site administrative support",
            "description": "Administrative support with in-person field work.",
        }
    )
    assert packet["execution_ready"] is False
    assert packet["status"] == "BLOCKED"
    assert "human_only_work" in packet["blockers"]


def test_blocks_unmatched_work():
    packet = build_work_packet(
        {
            "opportunity_title": "Unknown specialty",
            "description": "Perform an unspecified specialist service.",
        }
    )
    assert packet["execution_ready"] is False
    assert "no_confirmed_nova_capability" in packet["blockers"]
