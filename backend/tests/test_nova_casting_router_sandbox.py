"""Sandbox write routes stay behind the production-locked flag and accept no uploads."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "app/core/nova/creative_studio/casting_router_sandbox.py"
DRAFT = ROOT / "app/core/nova/creative_studio/casting_router_draft.py"


def test_sandbox_posts_exist_only_behind_the_flag():
    source = SANDBOX.read_text(encoding="utf-8")
    draft = DRAFT.read_text(encoding="utf-8")
    assert "@sandbox_router.post" in source
    assert "@router.post" not in draft
    assert "UploadFile" not in source
    assert "boto3" not in source
    assert "include_router(sandbox_router)" in draft
    assert "casting_db_models" not in draft
    tree = ast.parse(source)
    dependency = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "casting_sandbox_session")
    gate = dependency.body[0]
    assert isinstance(gate, ast.If)
    assert gate.test.operand.func.id == "casting_sandbox_writes_enabled"
    assert "external_delivery" in source
    assert '"external_delivery"] = False' in source
