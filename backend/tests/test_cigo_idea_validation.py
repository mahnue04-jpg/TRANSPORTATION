"""Fictional CIGO consumer idea-validation worksheet. No outbound sends and no video."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.cigo_idea_validation.router import STORE, router
from app.core.cigo_idea_validation.script import EXAMPLE, SCRIPT_ID, SCRIPT_TEXT
from app.core.cigo_idea_validation.service import demo_enabled

VALID = dict(EXAMPLE)


@pytest.fixture()
def client():
    STORE.reset()
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    STORE.reset()


def test_demo_stays_off_in_production(monkeypatch):
    monkeypatch.setenv("CIGO_IDEA_VALIDATION_DEMO", "1")
    monkeypatch.setenv("RUNTIME_ENVIRONMENT", "production")
    assert demo_enabled() is False
    monkeypatch.setenv("RUNTIME_ENVIRONMENT", "development")
    assert demo_enabled() is True
    monkeypatch.delenv("CIGO_IDEA_VALIDATION_DEMO")
    assert demo_enabled() is False


def test_main_mounts_the_worksheet_only_behind_the_flag():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "cigo_idea_validation_demo_enabled()" in main
    assert "if cigo_idea_validation_demo_enabled():" in main
    page = (ROOT / "static" / "cigo-idea-validation" / "index.html").read_text(encoding="utf-8")
    assert 'content="noindex, nofollow"' in page
    assert "does not submit anything to CIGO" in page
    assert "not assessment-ready" in page
    source = (ROOT / "app" / "core" / "cigo_idea_validation" / "service.py").read_text(encoding="utf-8")
    router_source = (ROOT / "app" / "core" / "cigo_idea_validation" / "router.py").read_text(encoding="utf-8")
    for banned in ("smtplib", "httpx", "requests", "boto3", "stripe"):
        assert banned not in source
        assert banned not in router_source


def test_script_stays_unrendered_and_assessment_is_not_ready(client: TestClient):
    evidence = client.get("/dev/cigo-idea-validation/evidence")
    assert evidence.status_code == 200
    body = evidence.json()
    assert body["assessment_ready"] is False
    assert body["video_rendered"] is False
    assert body["repeating_plate_created"] is False
    assert body["paid_provider_called"] is False
    assert body["commercial_use_cleared"] is False
    assert body["ip_agreement_signed"] is False
    assert body["submitted_to_cigo"] is False
    assert body["outbound_sends"] == 0
    assert body["provider"]["quoted_checkout_usd"] is None
    assert body["provider"]["charged_usd"] == 0
    assert body["provider"]["subscription_started"] is False
    assert body["provider"]["heygen_payg_watermark_free_commercial_mp4"] == "not_confirmed"
    assert body["script"]["id"] == SCRIPT_ID
    assert body["script"]["rendered"] is False
    assert body["script"]["text"] == SCRIPT_TEXT
    assert body["script"]["word_count"] == len(SCRIPT_TEXT.split())
    assert [step["id"] for step in body["workflow"]] == ["consumer", "idea", "assumption", "evidence", "result"]
    assert "Lease Lens" in body["script"]["text"]
    page = client.get("/dev/cigo-idea-validation")
    assert page.status_code == 200
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert "Consumer idea validation" in page.text


def test_create_duplicate_invalid_failure_and_export(client: TestClient):
    created = client.post("/dev/cigo-idea-validation/worksheets", json=VALID)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "created"
    assert body["record"]["id"].startswith("idea_")
    assert body["record"]["result"] == "reshape"
    assert body["record"]["evidence_is_fictional"] is True
    assert body["record"]["status"] == "worksheet_only"
    assert body["outbound_sends"] == 0
    assert created.headers["x-cigo-outbound-sends"] == "0"

    again = client.post(
        "/dev/cigo-idea-validation/worksheets",
        json={**VALID, "idea": "  lease   lens, a phone checklist that lists add-on fees before a first-time renter signs.  "},
    )
    assert again.status_code == 200
    assert again.json()["status"] == "duplicate"
    assert again.json()["record"]["id"] == body["record"]["id"]

    invalid = client.post(
        "/dev/cigo-idea-validation/worksheets",
        json={
            "consumer": "no",
            "job": "short",
            "idea": "too short",
            "assumption": "short",
            "evidence": "short",
            "evidence_is_fictional": False,
            "result": "launch",
            "consent": False,
        },
    )
    assert invalid.status_code == 422
    fields = invalid.json()["failure"]["fields"]
    assert set(fields) >= {"consumer", "job", "idea", "assumption", "evidence", "evidence_is_fictional", "result", "consent"}

    before = len(client.get("/dev/cigo-idea-validation/worksheets").json()["records"])
    failed = client.post(
        "/dev/cigo-idea-validation/worksheets",
        json={**VALID, "consumer": "Another fictional renter who should not be stored"},
        headers={"X-Cigo-Force-Failure": "store"},
    )
    assert failed.status_code == 503
    assert failed.json()["status"] == "failed"
    assert len(client.get("/dev/cigo-idea-validation/worksheets").json()["records"]) == before

    exported = client.get("/dev/cigo-idea-validation/export.json")
    assert exported.json()["assessment_ready"] is False
    assert exported.json()["outbound_sends"] == 0
    assert exported.json()["records"][0]["id"] == body["record"]["id"]
    csv_body = client.get("/dev/cigo-idea-validation/export.csv")
    assert csv_body.headers["content-type"].startswith("text/csv")
    assert "Lease Lens" in csv_body.text

    evidence = client.get("/dev/cigo-idea-validation/evidence").json()
    assert evidence["worksheet_count"] == 1
    assert evidence["assessment_ready"] is False
    assert evidence["video_rendered"] is False

    client.post("/dev/cigo-idea-validation/reset")
    assert client.get("/dev/cigo-idea-validation/worksheets").json()["records"] == []
    assert client.get("/dev/cigo-idea-validation/export.json").json()["outbound_sends"] == 0
