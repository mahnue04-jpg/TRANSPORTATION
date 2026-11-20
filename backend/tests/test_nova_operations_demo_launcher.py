"""Safety checks for loopback-only Nova Operations synthetic demo launcher."""
from __future__ import annotations

import pytest
from scripts.launch_nova_operations_demo import demo_environment


def test_launcher_generates_isolated_demo_settings():
    source = {
        "PATH": "/usr/bin", "HOME": "/tmp",
        "OPENAI_API_KEY": "must-not-inherit",
        "JWT_SECRET": "must-not-inherit",
        "SECRET_KEY": "must-not-inherit",
        "AMICOR_SEED_PASSWORD": "must-not-inherit",
        "APP_ENV": "development",
    }
    result = demo_environment(source)
    assert result["NOVA_DEMO_STANDALONE"] == "true"
    assert result["APP_ENV"] == "demo"
    assert result["AMICOR_ENVIRONMENT"] == "demo"
    assert result["NOVA_DEMO_OWNER_USER"] == "sample-owner"
    assert len(result["NOVA_DEMO_OWNER_PASSWORD"]) >= 24
    for secret in ("OPENAI_API_KEY", "JWT_SECRET", "SECRET_KEY", "AMICOR_SEED_PASSWORD", "DATABASE_URL"):
        assert secret not in result
    again = demo_environment(source)
    assert again["NOVA_DEMO_OWNER_PASSWORD"] != result["NOVA_DEMO_OWNER_PASSWORD"]


@pytest.mark.parametrize("key,value", [
    ("DATABASE_URL", "postgresql://prod:secret@database/amicor"),
    ("RENDER", "true"),
    ("RENDER_SERVICE_NAME", "amicor-health-isf"),
    ("RENDER_EXTERNAL_URL", "https://amicor-health-isf.onrender.com"),
])
def test_launcher_denies_connected_or_deployed_environments(key, value):
    with pytest.raises(RuntimeError):
        demo_environment({key: value})


def test_launcher_binds_only_loopback():
    from pathlib import Path
    import ast
    source = Path(__file__).resolve().parents[1] / "scripts/launch_nova_operations_demo.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    # Verify actual process launch arguments; never allow 0.0.0.0 or ::.
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "execve"]
    assert len(calls) == 1
    args = calls[0].args[1]
    assert isinstance(args, ast.List)
    literals = [x.value for x in args.elts if isinstance(x, ast.Constant)]
    assert "127.0.0.1" in literals
    assert "0.0.0.0" not in literals
