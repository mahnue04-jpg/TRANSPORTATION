"""Tests for guarded alternate startup without a live database or paid services."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "receptionist_staging_diagnostic_boot.py"


def load():
    spec = importlib.util.spec_from_file_location("receptionist_staging_diag_boot_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_guarded_migration_runs_before_diagnostic_exec(monkeypatch):
    module = load()
    calls = []
    base = SOURCE.parent.parent
    fake = types.SimpleNamespace(
        migrate_only=lambda: calls.append("guarded-migrate"),
        _backend_dir=lambda: base,
    )
    monkeypatch.setitem(sys.modules, "receptionist_staging_start", fake)
    monkeypatch.setattr(module.os, "chdir", lambda path: calls.append(("chdir", str(path))))
    monkeypatch.setattr(module.os, "execv", lambda path, args: calls.append(("exec", path, args)))
    module.main()
    assert calls[0] == "guarded-migrate"
    assert calls[1] == ("chdir", str(base))
    assert calls[2][0] == "exec"
    assert calls[2][1] == sys.executable
    assert calls[2][2][0:2] == [sys.executable, "-u"]
    assert calls[2][2][2].endswith("receptionist_uvicorn_diagnostic.py")


def test_bootstrap_does_not_bypass_guards():
    source = SOURCE.read_text(encoding="utf-8")
    assert "existing.migrate_only()" in source
    assert source.index("existing.migrate_only()") < source.index("os.execv(")
    for forbidden in ("create_all", "alembic upgrade head", "DATABASE_URL =", "TWILIO_", "Kling", "GOOGLE_CLIENT_SECRET"):
        assert forbidden not in source
