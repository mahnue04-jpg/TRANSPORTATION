"""Tests for owner-controlled Nova autonomous work execution."""
from app.core.nova.v3.autonomous_execution import (
    BLOCKED_EXTERNAL,
    OWNER_GATE,
    SAFE_INTERNAL,
    build_autonomous_execution_session,
    detect_vertical,
)


def test_delivery_work_builds_autonomous_internal_session():
    session = build_autonomous_execution_session(
        {
            "opportunity_title": "Remote delivery operations support",
            "company_name": "Example Courier",
            "description": (
                "Remote dispatch administration, shipment tracking, spreadsheet reporting, "
                "customer update drafts and proof-of-delivery organization."
            ),
            "requirements": "B2B contractor. No driving or physical delivery.",
        }
    )
    assert session["autonomous_execution_ready"] is True
    assert session["status"] == "READY_FOR_AUTONOMOUS_INTERNAL_WORK"
    assert session["vertical"]["vertical_id"] == "delivery_logistics"
    assert session["supported_vertical_work"]
    assert session["external_submission"] is False
    assert session["client_contact"] is False
    assert session["financial_execution"] is False


def test_vertical_detection_covers_requested_business_families():
    samples = {
        "delivery_logistics": "courier dispatch and shipment reporting",
        "property_management": "property management tenant maintenance tracking",
        "home_care_admin": "home care scheduling and non-clinical reporting",
        "staffing_recruiting": "staffing candidate pipeline reporting",
        "construction_services": "construction work order and project reporting",
    }
    for expected, description in samples.items():
        assert detect_vertical({"description": description})["vertical_id"] == expected


def test_external_actions_never_auto_advance():
    session = build_autonomous_execution_session(
        {
            "opportunity_title": "AI workflow automation vendor",
            "description": "Build workflow automation and API integration for business operations.",
        }
    )
    assert session["autonomous_execution_ready"] is True
    final_stage = session["stages"][-1]
    assert final_stage["status"] == "BLOCKED"
    assert final_stage["nova_may_advance"] is False
    assert session["production_deploy"] is False


def test_task_classifications_exposed_in_session():
    session = build_autonomous_execution_session(
        {
            "opportunity_title": "Administrative operations project",
            "description": "Organize tasks, prepare schedules, reports, documents and follow-up drafts.",
        }
    )
    tasks = session["stages"][1]["tasks"]
    assert tasks
    assert all(row["execution_class"] in {SAFE_INTERNAL, OWNER_GATE, BLOCKED_EXTERNAL} for row in tasks)
    assert any(row["nova_may_advance"] for row in tasks)


def test_human_only_work_remains_blocked():
    session = build_autonomous_execution_session(
        {
            "opportunity_title": "On-site delivery driver",
            "description": "Drive vehicle, lift packages and deliver in person.",
        }
    )
    assert session["autonomous_execution_ready"] is False
    assert session["status"] == "BLOCKED"


def test_owner_triggered_autonomous_start_creates_internal_engagement_and_safe_tasks(client=None):
    # API coverage lives in Work & Revenue integration tests; this unit-level guard
    # ensures the autonomous session exposes safe tasks and keeps external actions off.
    session = build_autonomous_execution_session(
        {
            "opportunity_title": "Remote logistics reporting support",
            "company_name": "Example Logistics",
            "description": "Remote dispatch administration, shipment tracking, spreadsheet reporting and document preparation.",
            "requirements": "B2B contractor. No driving or physical presence.",
        }
    )
    stage = next(row for row in session["stages"] if row["stage"] == "AUTONOMOUS_INTERNAL_EXECUTION")
    safe = [row for row in stage["tasks"] if row["nova_may_advance"]]
    assert session["autonomous_execution_ready"] is True
    assert safe
    assert all(row["execution_class"] == SAFE_INTERNAL for row in safe)
    assert session["external_submission"] is False
    assert session["client_contact"] is False
    assert session["financial_execution"] is False
