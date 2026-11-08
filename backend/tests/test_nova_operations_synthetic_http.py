"""HTTP acceptance checks for the UNREGISTERED synthetic demo adapter.

FastAPI dependencies here are synthetic fixture stand-ins; these tests do not
assert signed-JWT validation, public accessibility, or customer readiness.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel

SOURCE = Path(__file__).resolve().parents[1] / "app/core/nova/work_revenue/operations_synthetic_http.py"
BASE = "/api/nova/work/operations/synthetic-acceptance"
ENDPOINT = BASE + "/download"
SAMPLE = b"Name,Department\nAda,Operations\nMina,Research\n"


def _isolated_adapter(monkeypatch, *, tamper=False):
    """Run actual route AST in a lightweight synthetic-only FastAPI app."""
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node for node in tree.body
        if (
            isinstance(node, (ast.Assign, ast.ClassDef))
            and (isinstance(node, ast.ClassDef) and node.name == "SyntheticReviewDecision"
                 or isinstance(node, ast.Assign) and any(
                     isinstance(x, ast.Name) and x.id == "router" for x in node.targets))
        )
        or (isinstance(node, ast.FunctionDef) and node.name in {
            "_require_isolated_demo", "_review_db", "_reviewer", "_synthetic_csv",
            "preview_synthetic_acceptance", "review_synthetic_acceptance",
            "download_synthetic_acceptance", "synthetic_review_ui"
        })
    ]
    tree = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *selected,
    ], type_ignores=[])
    ast.fix_missing_locations(tree)

    def require_nova_access():
        return None

    def require_work_revenue_owner():
        raise HTTPException(status_code=401, detail="Owner sign-in required")

    def run_synthetic_demo(root):
        (root / "nova_synthetic_cleaned.csv").write_bytes(SAMPLE if not tamper else b"tampered")
        return {
            "review_state": "approved_by_synthetic_fixture",
            "sha256": hashlib.sha256(SAMPLE).hexdigest(),
        }

    namespace = dict(
        APIRouter=APIRouter, Depends=Depends, HTTPException=HTTPException,
        Response=Response, HTMLResponse=HTMLResponse, UserContext=SimpleNamespace,
        require_nova_access=require_nova_access,
        require_work_revenue_owner=require_work_revenue_owner,
        run_synthetic_demo=run_synthetic_demo,
        tempfile=tempfile, Path=Path, hashlib=hashlib, os=os, re=re,
        urlsplit=urlsplit, sqlite3=sqlite3, BaseModel=BaseModel,
        contextmanager=contextmanager,
    )
    exec(compile(tree, str(SOURCE), "exec"), namespace)
    app = FastAPI()
    app.include_router(namespace["router"])
    app.dependency_overrides[require_nova_access] = lambda: None
    return app, require_work_revenue_owner


def _enable_preview(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_OPERATIONS_SYNTHETIC_LEDGER", str(tmp_path / "demo-review.sqlite"))
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_SYNTHETIC_HTTP_ENABLED", "true")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://amicor-health-isf-pr-462.onrender.com")
    monkeypatch.setenv("RENDER_GIT_BRANCH", "feat/nova-operations-auth-handoff-integration-20261107")


def test_synthetic_download_requires_session(monkeypatch, tmp_path):
    _enable_preview(monkeypatch, tmp_path)
    app, owner = _isolated_adapter(monkeypatch)
    with TestClient(app) as client:
        assert client.get(ENDPOINT).status_code == 401


@pytest.mark.parametrize("change", [
    {"APP_ENV": "production"},
    {"AMICOR_ENVIRONMENT": "production"},
    {"NOVA_OPERATIONS_SYNTHETIC_HTTP_ENABLED": "false"},
    {"RENDER_EXTERNAL_URL": "https://amicor-health-isf.onrender.com"},
    {"RENDER_GIT_BRANCH": "main"},
    {"RENDER_GIT_BRANCH": ""},
])
def test_synthetic_download_fails_closed_if_not_isolated(monkeypatch, tmp_path, change):
    _enable_preview(monkeypatch, tmp_path)
    for key, val in change.items():
        monkeypatch.setenv(key, val)
    app, owner = _isolated_adapter(monkeypatch)
    app.dependency_overrides[owner] = lambda: SimpleNamespace(user_id="synthetic-owner")
    with TestClient(app) as client:
        assert client.get(ENDPOINT).status_code == 503


def test_synthetic_download_requires_explicit_review(monkeypatch, tmp_path):
    _enable_preview(monkeypatch, tmp_path)
    app, owner = _isolated_adapter(monkeypatch)
    app.dependency_overrides[owner] = lambda: SimpleNamespace(user_id="synthetic-owner")
    with TestClient(app) as client:
        assert client.get(ENDPOINT).status_code == 403
        preview = client.get(BASE + "/preview")
        assert preview.status_code == 200
        assert preview.json()["review_state"] == "awaiting_owner_review"
        assert preview.json()["csv_text"].encode() == SAMPLE
        decision = client.post(BASE + "/review", json={"approve": True})
        assert decision.status_code == 200
        assert decision.json()["review_state"] == "approved"
        result = client.get(ENDPOINT)
        assert result.status_code == 200
        assert result.content == SAMPLE
        assert result.headers["content-type"].startswith("text/csv")
        assert "attachment;" in result.headers["content-disposition"]
        assert result.headers["cache-control"] == "no-store"
        assert result.headers["x-nova-data-class"] == "synthetic-only"
        assert client.post(BASE + "/review", json={"approve": False}).status_code == 409


def test_rejection_and_different_owner_cannot_download(monkeypatch, tmp_path):
    _enable_preview(monkeypatch, tmp_path)
    app, owner = _isolated_adapter(monkeypatch)
    app.dependency_overrides[owner] = lambda: SimpleNamespace(user_id="reviewer-one")
    with TestClient(app) as client:
        assert client.post(BASE + "/review", json={"approve": False}).status_code == 200
        assert client.get(ENDPOINT).status_code == 403
        app.dependency_overrides[owner] = lambda: SimpleNamespace(user_id="reviewer-two")
        assert client.get(ENDPOINT).status_code == 403
        assert client.get(BASE + "/preview").json()["review_state"] == "awaiting_owner_review"


def test_synthetic_download_rejects_tampered_file(monkeypatch, tmp_path):
    _enable_preview(monkeypatch, tmp_path)
    app, owner = _isolated_adapter(monkeypatch, tamper=True)
    app.dependency_overrides[owner] = lambda: SimpleNamespace(user_id="synthetic-owner")
    with TestClient(app) as client:
        assert client.get(BASE + "/preview").status_code == 503
        assert client.post(BASE + "/review", json={"approve": True}).status_code == 503
        assert client.get(ENDPOINT).status_code == 503



def test_synthetic_review_screen_requires_owner_and_staging(monkeypatch, tmp_path):
    _enable_preview(monkeypatch, tmp_path)
    app, owner = _isolated_adapter(monkeypatch)
    with TestClient(app) as client:
        assert client.get(BASE + "/ui").status_code == 401
        app.dependency_overrides[owner] = lambda: SimpleNamespace(user_id="owner-demo")
        response = client.get(BASE + "/ui")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert response.headers["cache-control"] == "no-store"
        assert "id=\"approve\"" in response.text
        assert "id=\"reject\"" in response.text
        assert "id=\"download\"" in response.text
        assert '"/preview"' in response.text
        assert '"/review"' in response.text
        assert '"/download"' in response.text
        monkeypatch.setenv("APP_ENV", "production")
        assert client.get(BASE + "/ui").status_code == 503

def test_synthetic_adapter_is_not_registered():
    root = SOURCE.parents[1]
    # Registration must be an explicit, separately reviewed change.
    for entrypoint in (root / "main.py", root / "app/main.py"):
        if entrypoint.exists():
            assert "operations_synthetic_http" not in entrypoint.read_text(encoding="utf-8")
