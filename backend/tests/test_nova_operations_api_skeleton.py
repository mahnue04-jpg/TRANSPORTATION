"""Contract checks for the disabled Operations CSV API skeleton.

These tests avoid real customer data, storage, and external integrations.
"""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "app/core/nova/work_revenue/operations_csv_api.py"


def test_routes_remain_unregistered_and_fail_closed():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    routes = {
        "submit_csv_job", "csv_job_status", "csv_job_review", "csv_job_download"
    }
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert routes.issubset(functions)
    for name in routes:
        calls = [
            node for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "_disabled"
        ]
        assert calls, f"{name} must fail closed until integration is approved"
    source = SOURCE.read_text(encoding="utf-8")
    assert 'Depends(require_nova_access)' in source
    assert 'Depends(require_work_revenue_owner)' in source
    assert "status_code=503" in source
    assert "include_router" not in source


def test_no_customer_data_or_paid_provider_calls_in_skeleton():
    source = SOURCE.read_text(encoding="utf-8")
    for forbidden in ("UploadFile", "File(", "requests.", "httpx.", "fal_client", "stripe."):
        assert forbidden not in source


def test_no_implicit_router_registration_in_application_entrypoint():
    """The skeleton is intentionally not mounted by the application."""
    root = SOURCE.parents[3]
    candidate_paths = (
        root / "main.py",
        root / "app" / "main.py",
    )
    for candidate in candidate_paths:
        if candidate.exists():
            source = candidate.read_text(encoding="utf-8")
            assert "operations_csv_api" not in source
