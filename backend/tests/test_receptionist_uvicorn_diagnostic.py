"""Focused checks for staging-only receptionist Uvicorn diagnostics.

No Render access, database connections or external providers are required.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "receptionist_uvicorn_diagnostic.py"


def _load():
    spec = importlib.util.spec_from_file_location("receptionist_uvicorn_diagnostic_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_diagnostic_runs_uvicorn_on_expected_interface(monkeypatch, capsys):
    script = _load()
    calls = []
    fake = types.SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake)
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setattr(script.faulthandler, "enable", lambda **kwargs: None)
    monkeypatch.setattr(
        script.faulthandler, "dump_traceback_later",
        lambda seconds, **kwargs: calls.append(("trace", seconds, kwargs)),
    )

    script.main()

    assert calls[0][0] == "trace"
    assert calls[0][1] == 120
    assert calls[0][2]["repeat"] is True
    assert calls[1] == (("app.main:app",), {"host": "0.0.0.0", "port": 10000})
    assert "loading ASGI application" in capsys.readouterr().out


def test_diagnostic_has_no_database_or_provider_side_effects():
    source = SOURCE.read_text(encoding="utf-8")
    assert "DATABASE_URL" not in source
    assert "create_all" not in source
    assert "alembic upgrade" not in source
    assert "twilio" not in source.lower()
    assert "google" not in source.lower()
    assert "faulthandler.dump_traceback_later" in source
