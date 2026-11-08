"""Bounded owner-only CSV API checks with isolated FastAPI HTTP harness.

Contract harness validates download controls without importing the production
app or exposing credentials. Production JWT integration remains a release gate.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
CLEANUP_FILE = ROOT / "app/core/nova/work_revenue/operations_csv_cleanup.py"
API_FILE = ROOT / "app/core/nova/work_revenue/operations_owner_csv_api.py"

def _load_cleanup():
    module = types.ModuleType("nova_operations_csv_cleanup_isolated")
    module.__file__ = str(CLEANUP_FILE)
    sys.modules[module.__name__] = module
    exec(compile(CLEANUP_FILE.read_text(), str(CLEANUP_FILE), "exec"), module.__dict__)
    return module


def _load_app():
    cleanup = _load_cleanup()
    router = APIRouter(prefix="/operations")
    owner = SimpleNamespace(organization_id="test-owner-tenant")
    def require_owner():
        return owner
    tree = ast.parse(API_FILE.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "owner_csv_cleanup")
    ns = {
        "__name__": "isolated_http_contract", "router": router,
        "os": os, "Depends": Depends, "File": File, "Header": Header,
        "UploadFile": UploadFile, "HTTPException": HTTPException,
        "Response": Response, "UserContext": object,
        "LIMIT_BYTES": 1_000_000,
        "CSV_MIME_TYPES": {"text/csv", "application/csv", "application/vnd.ms-excel", "application/octet-stream"},
        "SpreadsheetInputError": cleanup.SpreadsheetInputError,
        "clean_csv_text": cleanup.clean_csv_text,
        "require_work_revenue_owner": require_owner,
    }
    code = compile(ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function], type_ignores=[]), str(API_FILE), "exec")
    exec(code, ns)
    app = FastAPI()
    app.include_router(router, prefix="/api/nova/work")
    return app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "true")
    with TestClient(_load_app()) as client:
        yield client


def post(client, content, *, headers=None, name="sample.csv", mime="text/csv"):
    return client.post("/api/nova/work/operations/csv-clean",
        files={"file": (name, content, mime)},
        headers=headers or {"X-Nova-Owner-Action": "process-csv-for-owner-review"})


def test_real_csv_bytes_downloaded_for_review_without_persistence(client):
    response = post(client, b"Name,Department\n Ada ,Operations\nAda,Operations\n,\nMina,Research\n")
    assert response.status_code == 200, response.text
    assert response.content == b"Name,Department\nAda,Operations\nMina,Research\n"
    assert response.headers["x-nova-input-rows"] == "4"
    assert response.headers["x-nova-output-rows"] == "2"
    assert response.headers["x-nova-owner-review-required"] == "true"
    assert "no-store" in response.headers["cache-control"]
    assert "attachment" in response.headers["content-disposition"]
    assert not hasattr(client.app.state, "artifacts")


def test_default_disabled(monkeypatch, client):
    monkeypatch.delenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED")
    assert post(client, b"A\n1\n").status_code == 503


def test_requires_explicit_owner_action_header(client):
    assert post(client, b"A\n1\n", headers={}).status_code == 403


@pytest.mark.parametrize("name,mime,expected", [
    ("notes.txt", "text/csv", 400),
    ("bad.csv", "application/pdf", 415),
    ("bad\x00.csv", "text/csv", 400),
])
def test_rejects_non_csv(client, name, mime, expected):
    assert post(client, b"A\n1\n", name=name, mime=mime).status_code == expected


def test_csv_limit_and_encoding(client):
    assert post(client, b"A\n" + b"x" * 1_000_001).status_code == 413
    assert post(client, b"A\n\xff\xfe").status_code == 400


def test_prevents_spreadsheet_formula_execution(client):
    result = post(client, b"Cell\n=2+2\n")
    assert result.status_code == 200
    assert result.content == b"Cell\n'=2+2\n"


def test_production_router_keeps_owner_dependencies_and_mounts_endpoint():
    source = (ROOT / "app/core/nova/work_revenue/router.py").read_text(encoding="utf-8")
    api_source = API_FILE.read_text(encoding="utf-8")
    assert "router.include_router(owner_csv_router)" in source
    assert "Depends(require_work_revenue_owner)" in api_source
    assert "Depends(require_nova_access)" in api_source
    assert 'prefix="/operations"' in api_source
    assert "NOVA_OPERATIONS_OWNER_CSV_ENABLED" in api_source
