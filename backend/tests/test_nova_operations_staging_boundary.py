"""Static fail-closed checks for the unregistered Operations staging router.

Use AST inspection to avoid importing the production Work & Revenue router into
the lightweight offline CI. This is NOT an integration test of live JWT auth.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app/core/nova/work_revenue/operations_staging_boundary.py"


def test_staging_approval_routes_remain_owner_gated_and_disabled():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    funcs = {
        node.name: node for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {"disabled_approval_staging", "disabled_review_staging"} <= funcs.keys()
    assert "Depends(require_nova_access)" in code
    assert "Depends(require_work_revenue_owner)" in code
    assert "owner_approval_identity(user)" in code
    assert "status_code=503" in code
    assert "approve_and_handoff_offline" not in code
    assert "review_approved_assignment_offline" not in code
    for function in funcs.values():
        calls = [
            n.func.id for n in ast.walk(function)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        assert "owner_approval_identity" in calls
        assert "HTTPException" in calls
        assert "Depends(require_work_revenue_owner)" in ast.unparse(function)


def test_staging_approval_router_not_registered_in_known_entrypoints():
    for path in (
        ROOT / "main.py",
        ROOT / "app/main.py",
        ROOT / "app/core/nova/router.py",
        ROOT / "app/core/nova/work_revenue/router.py",
    ):
        if path.exists():
            assert "operations_staging_boundary" not in path.read_text(encoding="utf-8")
