"""Mock CIGO product-validation demo. No outbound sends."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.cigo_validation.router import STORE, router
from app.core.cigo_validation.service import demo_enabled

VALID = {
    "idea": "A desk assistant that drafts the weekly owner brief.",
    "budget": "1500.00",
    "currency": "usd",
    "email": "",
    "follow_up": "none",
    "consent": True,
}


@pytest.fixture()
def client():
    STORE.reset()
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    STORE.reset()


def test_demo_stays_off_in_production(monkeypatch):
    monkeypatch.setenv("CIGO_VALIDATION_DEMO", "1")
    monkeypatch.setenv("RUNTIME_ENVIRONMENT", "production")
    assert demo_enabled() is False
    monkeypatch.setenv("RUNTIME_ENVIRONMENT", "development")
    assert demo_enabled() is True
    monkeypatch.delenv("CIGO_VALIDATION_DEMO")
    assert demo_enabled() is False


def test_main_mounts_the_demo_only_behind_the_flag():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "cigo_validation_demo_enabled()" in main
    assert "if cigo_validation_demo_enabled():" in main
    page = (ROOT / "static" / "cigo-validation" / "index.html").read_text(encoding="utf-8")
    assert 'content="noindex, nofollow"' in page
    assert "does not email anyone" in page
    source = (ROOT / "app" / "core" / "cigo_validation" / "service.py").read_text(encoding="utf-8")
    router_source = (ROOT / "app" / "core" / "cigo_validation" / "router.py").read_text(encoding="utf-8")
    for banned in ("smtplib", "httpx", "requests", "boto3", "stripe"):
        assert banned not in source
        assert banned not in router_source


def test_create_duplicate_invalid_failure_and_export(client: TestClient):
    created = client.post("/dev/cigo-validation/submissions", json=VALID)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "created"
    assert body["record"]["id"].startswith("cigo_")
    assert body["record"]["currency"] == "USD"
    assert body["record"]["budget"] == "1500.00"
    assert body["record"]["email"] == ""
    assert body["alert"]["sent"] is False
    assert body["alert"]["destination"] is None
    assert body["alert"]["status"] == "suppressed_no_outbound"
    assert body["outbound_sends"] == 0
    assert created.headers["x-robots-tag"] == "noindex, nofollow"
    assert created.headers["x-cigo-outbound-sends"] == "0"

    again = client.post(
        "/dev/cigo-validation/submissions",
        json={**VALID, "idea": "  a   desk assistant that drafts the weekly owner brief.  "},
    )
    assert again.status_code == 200
    assert again.json()["status"] == "duplicate"
    assert again.json()["record"]["id"] == body["record"]["id"]

    other = client.post("/dev/cigo-validation/submissions", json={**VALID, "email": "owner@example.com", "follow_up": "email"})
    assert other.status_code == 201
    assert other.json()["record"]["id"] != body["record"]["id"]

    invalid = client.post(
        "/dev/cigo-validation/submissions",
        json={"idea": "too short", "budget": "-5", "currency": "US$", "email": "not-an-email", "follow_up": "phone", "consent": False},
    )
    assert invalid.status_code == 422
    fields = invalid.json()["failure"]["fields"]
    assert set(fields) >= {"idea", "budget", "currency", "email", "follow_up", "consent"}

    missing_email = client.post("/dev/cigo-validation/submissions", json={**VALID, "idea": "Another idea that needs an email follow-up.", "follow_up": "email"})
    assert missing_email.status_code == 422
    assert "email" in missing_email.json()["failure"]["fields"]

    cents = client.post("/dev/cigo-validation/submissions", json={**VALID, "idea": "A third idea with too many budget decimals.", "budget": "10.999"})
    assert cents.status_code == 422

    before = len(client.get("/dev/cigo-validation/records").json()["records"])
    failed = client.post(
        "/dev/cigo-validation/submissions",
        json={**VALID, "idea": "This idea should not be stored during the failure."},
        headers={"X-Cigo-Force-Failure": "store"},
    )
    assert failed.status_code == 503
    assert failed.json()["status"] == "failed"
    assert len(client.get("/dev/cigo-validation/records").json()["records"]) == before

    records = client.get("/dev/cigo-validation/records").json()["records"]
    assert [row["id"] for row in records] == [body["record"]["id"], other.json()["record"]["id"]]
    alerts = client.get("/dev/cigo-validation/alerts").json()["alerts"]
    assert alerts and all(item["sent"] is False for item in alerts)
    failures = client.get("/dev/cigo-validation/failures").json()["failures"]
    assert {item["kind"] for item in failures} >= {"invalid_input", "store_unavailable"}

    exported = client.get("/dev/cigo-validation/export.json")
    assert exported.json()["outbound_sends"] == 0
    assert exported.json()["records"][0]["id"] == body["record"]["id"]
    csv_body = client.get("/dev/cigo-validation/export.csv")
    assert csv_body.headers["content-type"].startswith("text/csv")
    assert body["record"]["id"] in csv_body.text
    assert "A desk assistant that drafts the weekly owner brief." in csv_body.text

    page = client.get("/dev/cigo-validation")
    assert page.status_code == 200
    assert "Product validation demo" in page.text
    assert page.headers["x-robots-tag"] == "noindex, nofollow"

    client.post("/dev/cigo-validation/reset")
    assert client.get("/dev/cigo-validation/records").json()["records"] == []
    assert client.get("/dev/cigo-validation/alerts").json()["alerts"] == []
    assert client.get("/dev/cigo-validation/failures").json()["failures"] == []
    assert client.get("/dev/cigo-validation/export.json").json()["outbound_sends"] == 0
