"""Standalone local-only Operations review demo: authenticated HTTP acceptance.

No Render, production services or customer files are accessed.
"""
import base64
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setenv("NOVA_DEMO_STANDALONE", "true")
    monkeypatch.setenv("APP_ENV", "demo")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "demo")
    monkeypatch.setenv("NOVA_DEMO_OWNER_USER", "synthetic-owner")
    monkeypatch.setenv("NOVA_DEMO_OWNER_PASSWORD", "fixture-only-very-long-unique-password-4567")
    for key in ("DATABASE_URL", "RENDER_EXTERNAL_URL", "RENDER_SERVICE_NAME", "RENDER"):
        monkeypatch.delenv(key, raising=False)
    module = importlib.import_module("scripts.nova_operations_standalone_demo")
    auth = "Basic " + base64.b64encode(
        b"synthetic-owner:fixture-only-very-long-unique-password-4567"
    ).decode("ascii")
    return module, {"Authorization": auth}


def test_local_owner_review_and_download(fixture):
    module, headers = fixture
    # Review choices persisted between requests but not to application DB.
    with TestClient(module.app) as client:
        assert client.get(module.BASE + "/ui").status_code == 401
        assert client.get(module.BASE + "/ui", headers=headers).status_code == 200
        view = client.get(module.BASE + "/preview", headers=headers)
        assert view.status_code == 200
        assert view.json()["data_class"] == "synthetic_only"
        assert "Ada,Operations" in view.json()["csv_text"]
        assert client.get(module.BASE + "/download", headers=headers).status_code == 403
        request_headers = {**headers, "X-Nova-Demo-Action": "review"}
        approved = client.post(module.BASE + "/review", headers=request_headers, json={"approve": True})
        assert approved.status_code == 200
        assert approved.json()["review_state"] == "approved"
        file = client.get(module.BASE + "/download", headers=headers)
        assert file.status_code == 200
        assert file.content == b"Name,Department\nAda,Operations\nMina,Research\n"
        assert file.headers["x-nova-data-class"] == "synthetic-only"
        assert client.post(module.BASE + "/review", headers=request_headers, json={"approve": False}).status_code == 409


def test_local_owner_auth_and_csrf_controls(fixture):
    module, headers = fixture
    with TestClient(module.app) as client:
        assert client.get(module.BASE + "/preview").status_code == 401
        assert client.get(module.BASE + "/download", headers={"Authorization": "Basic Zm9vOmJhcg=="}).status_code == 401
        assert client.post(module.BASE + "/review", headers=headers, json={"approve": True}).status_code == 403
        assert client.post(module.BASE + "/review", headers={
            **headers, "X-Nova-Demo-Action": "review", "Origin": "https://foreign.invalid",
        }, json={"approve": True}).status_code == 403


@pytest.mark.parametrize("key,value", [
    ("APP_ENV", "production"),
    ("AMICOR_ENVIRONMENT", "production"),
    ("DATABASE_URL", "postgresql://example.invalid/production"),
    ("RENDER", "true"),
    ("NOVA_DEMO_STANDALONE", "false"),
])
def test_local_demo_disabled_outside_isolated_mode(fixture, monkeypatch, key, value):
    module, headers = fixture
    monkeypatch.setenv(key, value)
    with TestClient(module.app) as client:
        assert client.get(module.BASE + "/ui", headers=headers).status_code == 503
        assert client.get(module.BASE + "/preview", headers=headers).status_code == 503


def test_standalone_server_not_registered_in_main():
    root = Path(__file__).resolve().parents[1]
    assert "nova_operations_standalone_demo" not in (root / "app/main.py").read_text()
