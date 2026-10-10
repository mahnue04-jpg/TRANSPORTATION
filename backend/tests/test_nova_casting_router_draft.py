"""Static test: dormant casting router reuses Nova auth and is never registered."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app/core/nova/creative_studio/casting_router_draft.py"


def test_dormant_casting_router_requires_existing_nova_login():
    source = ROUTER.read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    creative = (ROOT / "app/core/nova/creative_studio/router.py").read_text(encoding="utf-8")
    assert "get_current_user_context" in source
    assert "Depends(get_current_user_context)" in source
    assert '"enabled": False' in source
    assert '"applications_enabled": False' in source
    assert '"media_uploads_enabled": False' in source
    assert "casting_router_draft" not in main
    assert "casting_router_draft" not in creative


def test_application_route_placeholder_is_disabled_even_for_authenticated_users():
    source = ROUTER.read_text(encoding="utf-8")
    assert 'router.get("/organizations/{organization_id}/applications/{application_id}")' in source
    assert 'user: UserContext = Depends(get_current_user_context)' in source
    assert 'status_code=503' in source
    assert 'Casting application access is not enabled' in source


def test_router_has_db_read_wiring_but_immutable_off_switch():
    src = ROUTER.read_text(encoding="utf-8")
    assert 'CASTING_READ_ENABLED = False' in src
    assert 'db: Session = Depends(get_db)' in src
    assert 'read_casting_application_for_nova_user(' in src
    assert 'except CastingAccessDenied:' in src


def test_read_route_returns_service_unavailable_without_touching_db():
    import ast
    source = (ROOT / "app/core/nova/creative_studio/casting_router_draft.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    route = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == "casting_application_read_draft")
    gate = next(node for node in route.body if isinstance(node, ast.If))
    assert isinstance(gate.test, ast.UnaryOp) and isinstance(gate.test.op, ast.Not)
    assert isinstance(gate.test.operand, ast.Name) and gate.test.operand.id == "CASTING_READ_ENABLED"
    # The unconditional disabled gate precedes any database service call.
    calls = [node for node in ast.walk(route) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "read_casting_application_for_nova_user"]
    assert len(calls) == 1
    assert route.body.index(gate) < next(i for i, stmt in enumerate(route.body)
        if any(item is calls[0] for item in ast.walk(stmt)))
