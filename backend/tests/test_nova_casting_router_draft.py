"""Casting routes reuse Nova auth, stay default-off, and do not open a read session while disabled."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app/core/nova/creative_studio/casting_router_draft.py"


def test_casting_router_is_mounted_without_importing_models():
    source = ROUTER.read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    creative = (ROOT / "app/core/nova/creative_studio/router.py").read_text(encoding="utf-8")
    assert "get_current_user_context" in source
    assert "Depends(get_current_user_context)" in source
    assert '"enabled": False' in source
    assert '"applications_enabled": False' in source
    assert '"media_uploads_enabled": False' in source
    assert "nova_casting_router" in main
    assert "include_router(nova_casting_router)" in main
    assert "casting_db_models" not in main
    assert "casting_db_reads" not in main
    assert "casting_db_models" not in source
    assert "/api/nova/casting/" not in creative
    assert "casting_router_draft" not in creative
    assert "@router.post" not in source
    assert "UploadFile" not in source


def test_application_route_is_disabled_until_the_staging_flag_passes():
    source = ROUTER.read_text(encoding="utf-8")
    assert 'router.get(\n    "/organizations/{organization_id}/applications/{application_id}",' in source
    assert 'user: UserContext = Depends(get_current_user_context)' in source
    assert "status_code=503" in source
    assert "Casting application access is not enabled" in source
    assert "casting_staging_reads_enabled" in source


def test_read_routes_keep_the_flag_ahead_of_database_imports():
    source = ROUTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for name, callee in (
        ("casting_application_read_draft", "read_casting_application_for_nova_user"),
        ("casting_campaign_read_draft", "read_casting_campaign_for_nova_user"),
    ):
        route = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        gate = next(node for node in route.body if isinstance(node, ast.If))
        assert isinstance(gate.test, ast.UnaryOp) and isinstance(gate.test.op, ast.Not)
        assert isinstance(gate.test.operand, ast.Call)
        assert isinstance(gate.test.operand.func, ast.Name)
        assert gate.test.operand.func.id == "casting_staging_reads_enabled"
        calls = [
            node for node in ast.walk(route)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == callee
        ]
        assert len(calls) == 1
        assert route.body.index(gate) < next(
            i for i, stmt in enumerate(route.body) if any(item is calls[0] for item in ast.walk(stmt))
        )


def test_session_dependency_checks_the_flag_before_opening_a_session():
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    dependency = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "casting_read_session")
    gate = dependency.body[0]
    assert isinstance(gate, ast.If)
    assert isinstance(gate.test, ast.UnaryOp) and isinstance(gate.test.operand, ast.Call)
    assert gate.test.operand.func.id == "casting_staging_reads_enabled"
    session_uses = [
        node for node in ast.walk(dependency)
        if isinstance(node, ast.Name) and node.id == "SessionLocal"
    ]
    assert session_uses
    assert dependency.body.index(gate) < next(
        i for i, stmt in enumerate(dependency.body) if any(item in session_uses for item in ast.walk(stmt))
    )
