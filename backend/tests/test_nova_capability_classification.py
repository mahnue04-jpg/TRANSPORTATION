"""Duty-based capability classification. Titles do not decide the class."""
from __future__ import annotations

from app.core.nova.v3.live_qualification import qualify_live_job
from app.core.nova.work_revenue.capability_classification import (
    CANNOT_PERFORM,
    CAN_PERFORM,
    INSUFFICIENT_INFORMATION,
    NEEDS_OWNER_REVIEW,
    classify_opportunity_capability,
)
from app.core.nova.work_revenue.fixtures import simulated_opportunities
from app.core.nova.work_revenue.flags import EXTERNAL_SUBMISSION_ENABLED, FINANCIAL_ACTIONS_ENABLED
from app.core.nova.work_revenue.qualifier import qualify_opportunity


def _class(payload: dict) -> dict:
    return classify_opportunity_capability(payload)


def test_delivery_driver_cannot_perform() -> None:
    result = _class(
        {
            "opportunity_title": "Delivery driver",
            "description": "Driving required to operate a vehicle and deliver packages each day.",
            "physical_presence_required": "true",
            "engagement_type": "contract",
        }
    )
    assert result["capability_classification"] == CANNOT_PERFORM
    assert result["required_physical_presence"] == "YES"
    assert result["auto_prepare_allowed"] is False
    assert any("drive" in item for item in result["nova_cannot_do"])
    assert any("separately" in item for item in result["nova_can_do"])


def test_warehouse_physical_associate_cannot_perform() -> None:
    result = _class(next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-warehouse"))
    assert result["capability_classification"] == CANNOT_PERFORM
    assert result["required_physical_presence"] == "YES"
    assert any("lifting" in item or "picking" in item for item in result["nova_cannot_do"])
    assert result["auto_prepare_allowed"] is False


def test_registered_nurse_cannot_perform() -> None:
    result = _class(next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-rn"))
    assert result["capability_classification"] == CANNOT_PERFORM
    assert result["required_license_or_credential"] == "RN license"
    assert any("nursing" in item for item in result["nova_cannot_do"])
    assert any("non-clinical" in item for item in result["nova_can_do"])
    assert result["auto_prepare_allowed"] is False


def test_missing_role_is_insufficient() -> None:
    result = _class(next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-missing"))
    assert result["capability_classification"] == INSUFFICIENT_INFORMATION
    assert result["blocking_reason"] == "insufficient duties/deliverables"
    assert result["auto_prepare_allowed"] is False


def test_title_alone_does_not_classify_driver_or_warehouse() -> None:
    driver = _class({"opportunity_title": "Delivery driver", "description": "", "physical_presence_required": "unknown"})
    warehouse = _class({"opportunity_title": "Warehouse associate", "description": "", "physical_presence_required": "unknown"})
    assert driver["capability_classification"] == INSUFFICIENT_INFORMATION
    assert warehouse["capability_classification"] == INSUFFICIENT_INFORMATION
    assert driver["title_used_for_decision"] is False


def test_remote_admin_digital_can_perform() -> None:
    result = _class(
        {
            "opportunity_title": "Remote administrative support contractor",
            "description": (
                "Vendor contract for research, spreadsheet cleanup, reporting, document preparation, "
                "data organization, workflow documentation, and drafting communications. Fully remote."
            ),
            "physical_presence_required": "false",
            "engagement_type": "contract",
        }
    )
    assert result["capability_classification"] == CAN_PERFORM
    assert result["owner_review_needed"] is False
    assert result["required_physical_presence"] == "NO"
    assert "research" in result["capability_registry_matches"]


def test_simulated_remote_admin_fixture_can_perform() -> None:
    result = _class(next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-admin-remote"))
    assert result["capability_classification"] == CAN_PERFORM


def test_admin_with_unclear_ai_policy_needs_owner_review() -> None:
    result = _class(
        {
            "opportunity_title": "Remote administrative support",
            "description": "Administrative support, spreadsheet work, and reporting. AI use policy unclear.",
            "physical_presence_required": "false",
            "engagement_type": "contract",
        }
    )
    assert result["capability_classification"] == NEEDS_OWNER_REVIEW
    assert result["owner_review_needed"] is True
    assert "AI-use policy" in result["owner_review_reason"]


def test_warehouse_spreadsheet_title_can_perform_from_duties() -> None:
    payload = {
        "opportunity_title": "Warehouse inventory spreadsheet analysis",
        "description": "Remote vendor contract to analyze inventory spreadsheets and produce reports.",
        "physical_presence_required": "false",
        "engagement_type": "contract",
    }
    result = _class(payload)
    assert result["capability_classification"] == CAN_PERFORM
    qualified = qualify_opportunity(payload)
    assert qualified["outcome"] == "NOVA_CAN_PERFORM"
    assert qualified["capability_classification"] == CAN_PERFORM
    assert qualified["title_used_for_decision"] is False


def test_healthcare_document_admin_without_clinical_practice_can_perform() -> None:
    result = _class(
        {
            "opportunity_title": "Healthcare document administrator",
            "description": "Prepare documents and organize records for a clinic office. Remote vendor contract.",
            "physical_presence_required": "false",
            "engagement_type": "contract",
        }
    )
    assert result["capability_classification"] == CAN_PERFORM
    assert result["required_license_or_credential"] == ""


def test_w2_employee_role_cannot_perform() -> None:
    result = _class(
        {
            "opportunity_title": "Remote operations assistant",
            "description": "Spreadsheet reporting and research as a W-2 employee role.",
            "physical_presence_required": "false",
            "engagement_type": "w2",
        }
    )
    assert result["capability_classification"] == CANNOT_PERFORM
    assert any("W-2" in item for item in result["nova_cannot_do"])
    assert result["auto_prepare_allowed"] is False


def test_licensed_professional_task_cannot_perform() -> None:
    result = _class(
        {
            "opportunity_title": "Contract advisor",
            "description": "Attorney must provide legal advice and a legal opinion.",
            "physical_presence_required": "false",
            "engagement_type": "contract",
        }
    )
    assert result["capability_classification"] == CANNOT_PERFORM
    assert result["required_license_or_credential"] == "licensed professional credential"


def test_physical_presence_required_cannot_perform() -> None:
    result = _class(
        {
            "opportunity_title": "Research contractor",
            "description": "Research and reporting deliverables.",
            "physical_presence_required": "true",
            "engagement_type": "contract",
        }
    )
    assert result["capability_classification"] == CANNOT_PERFORM
    assert result["required_physical_presence"] == "YES"


def test_valid_b2b_digital_contract_can_perform() -> None:
    result = _class(
        {
            "opportunity_title": "B2B reporting engagement",
            "description": "B2B vendor contract for research, spreadsheet analysis, and reporting. Fully remote.",
            "physical_presence_required": "false",
            "engagement_type": "contract",
        }
    )
    assert result["capability_classification"] == CAN_PERFORM
    assert result["auto_prepare_allowed"] is True


def test_cannot_and_insufficient_cannot_auto_prepare() -> None:
    driver = qualify_live_job(
        {
            "title": "Delivery driver",
            "description": "Driving required to operate a vehicle daily. Vendor contract. Research is not the job.",
            "source_url": "https://example.invalid/driver",
            "compensation_text": "$20/hr",
            "job_type": "contract",
            "source_attribution": "Example",
            "physical_presence_required": "true",
        }
    )
    missing = qualify_live_job(
        {
            "title": "Role not described",
            "description": "",
            "source_url": "https://example.invalid/missing",
            "compensation_text": "$20/hr",
            "job_type": "contract",
            "source_attribution": "Example",
        }
    )
    assert driver["capability_classification"] == CANNOT_PERFORM
    assert driver["auto_prepare_allowed"] is False
    assert driver["external_submission"] is False
    assert driver["financial_execution"] is False
    assert missing["capability_classification"] == INSUFFICIENT_INFORMATION
    assert missing["auto_prepare_allowed"] is False
    assert missing["qualification_status"] != "QUALIFIED"


def test_external_submission_and_financial_execution_remain_off() -> None:
    assert EXTERNAL_SUBMISSION_ENABLED is False
    assert FINANCIAL_ACTIONS_ENABLED is False
    b2b = qualify_live_job(
        {
            "title": "B2B Data Reporting Project",
            "company_name": "Northwind Analytics LLC",
            "description": (
                "Vendor / B2B project-based engagement. Independent contractor or business vendor welcome. "
                "Deliverables: research, data analysis, and reporting documentation. AI tools allowed. "
                "No membership fee. No upfront fee."
            ),
            "source_url": "https://remotive.com/remote-jobs/northwind-b2b-reporting",
            "compensation_text": "$2,500 per project",
            "job_type": "contract",
            "source_attribution": "Remotive",
        }
    )
    assert b2b["qualification_status"] == "QUALIFIED"
    assert b2b["auto_prepare_allowed"] is True
    assert b2b["external_submission"] is False
    assert b2b["financial_execution"] is False
