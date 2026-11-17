"""Regression checks for diagnostic subprocess ASGI import path.

The diagnostic script is exec'd by filename from backend/scripts; in that
execution mode sys.path[0] points at scripts, not backend. The app package must
be explicitly made importable before calling uvicorn.run.
"""
from pathlib import Path


def test_uvicorn_diagnostic_inserts_backend_before_loading_app():
    script = Path(__file__).resolve().parents[1] / "scripts" / "receptionist_uvicorn_diagnostic.py"
    source = script.read_text()
    assert 'backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))' in source
    assert "sys.path.insert(0, backend_dir)" in source
    assert source.index("sys.path.insert(0, backend_dir)") < source.index('uvicorn.run("app.main:app"')


def test_diagnostic_does_not_disable_existing_guards():
    script = Path(__file__).resolve().parents[1] / "scripts" / "receptionist_staging_diagnostic_boot.py"
    source = script.read_text()
    assert "existing.migrate_only()" in source
    assert 'os.execv(sys.executable, [sys.executable, "-u", str(script)])' in source
