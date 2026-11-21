"""Contract tests for read-only Work & Revenue -> Operations intake readiness."""
from types import SimpleNamespace
from pathlib import Path
import importlib.util

# This pure read-only contract deliberately runs without the production app,
# whose package initializer imports FastAPI and live application services.
SOURCE = (Path(__file__).resolve().parents[1] /
          "app/core/nova/work_revenue/operations_intake_readiness.py")
_spec = importlib.util.spec_from_file_location("nova_intake_contract_only", SOURCE)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
assess_operations_readiness = _module.assess_operations_readiness


def opportunity(**kwargs):
    return SimpleNamespace(
        opportunity_id=kwargs.get("opportunity_id", "opp-fixture-1"),
        organization_id=kwargs.get("organization_id", "tenant-fixture-a"),
        archived=kwargs.get("archived", False),
    )


def engagement(**kwargs):
    return {
        "engagement_id": "eng-fixture-1",
        "opportunity_id": kwargs.get("opportunity_id", "opp-fixture-1"),
        "organization_id": kwargs.get("organization_id", "tenant-fixture-a"),
        "status": kwargs.get("status", "ACTIVE"),
        "blockers": kwargs.get("blockers", ""),
        "tasks": kwargs.get("tasks", [
            {"task_id": "task-1", "title": "Clean synthetic spreadsheet",
             "responsible_party": "NOVA", "status": "NOT_STARTED", "review_required": True}
        ]),
    }


def test_unlinked_lead_is_not_represented_as_client_work():
    result = assess_operations_readiness(opportunity(), None)
    assert result["readiness"] == "blocked"
    assert result["engagement_id"] is None
    assert result["handoff_created"] is False
    assert result["execution_authorized"] is False
    assert result["payment_or_revenue_confirmed"] is False
    assert any("engagement" in x.lower() for x in result["required_owner_actions"])


def test_linked_engagement_still_requires_owner_and_data_approval():
    result = assess_operations_readiness(opportunity(), engagement())
    assert result["readiness"] == "owner_review_required"
    assert result["engagement_id"] == "eng-fixture-1"
    assert result["nova_task_previews"][0]["review_required"] is True
    assert result["execution_authorized"] is False
    assert result["customer_upload_enabled"] is False
    assert any("customer" in x.lower() for x in result["required_owner_actions"])
    assert any("storage" in x.lower() for x in result["required_owner_actions"])


def test_cross_tenant_engagement_is_not_linked():
    result = assess_operations_readiness(opportunity(), engagement(organization_id="tenant-other"))
    assert result["readiness"] == "blocked"
    assert result["engagement_id"] is None
    assert result["nova_task_previews"] == []


def test_archived_lead_and_blockers_block_intake():
    result = assess_operations_readiness(opportunity(archived=True), engagement(blockers="Awaiting customer signature"))
    assert result["readiness"] == "blocked"
    assert any("blockers" in x.lower() for x in result["required_owner_actions"])


def test_tenant_identity_cannot_be_global():
    import pytest
    with pytest.raises(ValueError):
        assess_operations_readiness(opportunity(organization_id="global"), None)


def test_no_suitable_task_is_not_a_job():
    result = assess_operations_readiness(opportunity(), engagement(tasks=[]))
    assert result["nova_task_previews"] == []
    assert any("bounded" in x.lower() for x in result["required_owner_actions"])
    assert result["handoff_created"] is False


def test_owner_only_route_exists_without_write_calls():
    from pathlib import Path
    import ast
    source = (Path(__file__).resolve().parents[1] /
              "app/core/nova/work_revenue/router.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "operations_intake_readiness")
    body = ast.unparse(target)
    assert "Depends(require_work_revenue_owner)" in body
    assert "service.get_opportunity(" in body
    assert "service.list_engagements(" in body
    assert "assess_operations_readiness(" in body
    for blocked in ("approve_and_handoff", "enqueue_job", "create_engagement", "send_email", "submit_application"):
        assert blocked not in body
