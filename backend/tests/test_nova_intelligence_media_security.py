"""Security checks for the default-off synthetic media slice."""
from __future__ import annotations

import socket
import urllib.request
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.intelligence.fixtures import resolve_allowlisted_fixture
from app.core.nova.intelligence.jobs import reset_jobs
from app.core.nova.intelligence.router import router
from app.core.nova.intelligence.ssrf import UnsafeMediaUrl, validate_https_url

ALLOWLIST_URL = "https://fixtures.nova.invalid/synthetic/meeting-clip-01"
JOBS = "/api/nova/intelligence/media/jobs"
DEMO = "/nova/intelligence/media-demo"
UNKNOWN_JOB = "00000000-0000-4000-8000-000000000099"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("NOVA_INTELLIGENCE_MEDIA", raising=False)
    reset_jobs()
    yield
    reset_jobs()


@pytest.fixture
def no_network(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)


def _user(tenant_id: str) -> UserContext:
    return UserContext(
        user_id=f"user-{tenant_id}",
        email=f"{tenant_id}@example.invalid",
        role="staff",
        organization_id=tenant_id,
    )


def _client(tenant: str | None = "tenant-a", explode: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if explode:
        def _boom():
            raise AssertionError("auth should not run while the flag is off")

        app.dependency_overrides[get_current_user_context] = _boom
    elif tenant is not None:
        app.dependency_overrides[get_current_user_context] = lambda tenant_id=tenant: _user(tenant_id)
    return TestClient(app)


def _payload(source_type: str = "fixture", value: str = "meeting-clip-01", **extra) -> dict:
    body = {
        "source": {"type": source_type, "value": value},
        "media_type": extra.pop("media_type", "video/mp4"),
        "declared_bytes": extra.pop("declared_bytes", 1024),
    }
    body.update(extra)
    return body


def test_flag_off_hides_routes_before_auth():
    client = _client(explode=True)
    job = f"{JOBS}/{UNKNOWN_JOB}"
    assert client.post(JOBS, json=_payload()).status_code == 404
    assert client.get(job).status_code == 404
    assert client.get(job + "/result").status_code == 404
    assert client.delete(job).status_code == 404
    demo = client.get(DEMO)
    assert demo.status_code == 404
    assert demo.json() == {"detail": "Not found"}


@pytest.mark.parametrize("raw", ["", "0", "true", "TRUE", "yes", "on", "1 ", " 1", "11"])
def test_flag_must_be_exactly_one(monkeypatch, raw):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", raw)
    client = _client(explode=True)
    assert client.post(JOBS, json=_payload()).status_code == 404
    assert client.get(DEMO).status_code == 404


def test_unauthenticated_calls_return_401(monkeypatch):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    client = _client(tenant=None)
    response = client.post(JOBS, json=_payload())
    assert response.status_code == 401
    assert client.get(DEMO).status_code == 401
    assert client.get(f"{JOBS}/{UNKNOWN_JOB}").status_code == 401


def test_missing_tenant_is_rejected(monkeypatch):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id="user-x",
        email="x@example.invalid",
        role="staff",
        organization_id=None,
    )
    client = TestClient(app)
    response = client.post(JOBS, json=_payload())
    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant context required"


def test_cross_tenant_matches_unknown_job(monkeypatch):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    app = FastAPI()
    app.include_router(router)
    holder = {"tenant": "tenant-a"}

    def _current():
        return _user(holder["tenant"])

    app.dependency_overrides[get_current_user_context] = _current
    client = TestClient(app)
    created = client.post(JOBS, json=_payload())
    assert created.status_code == 201
    job_id = created.json()["job_id"]
    holder["tenant"] = "tenant-b"
    foreign_status = client.get(f"{JOBS}/{job_id}")
    foreign_result = client.get(f"{JOBS}/{job_id}/result")
    foreign_delete = client.delete(f"{JOBS}/{job_id}")
    unknown_status = client.get(f"{JOBS}/{UNKNOWN_JOB}")
    unknown_result = client.get(f"{JOBS}/{UNKNOWN_JOB}/result")
    unknown_delete = client.delete(f"{JOBS}/{UNKNOWN_JOB}")
    assert foreign_status.status_code == unknown_status.status_code == 404
    assert foreign_status.json() == unknown_status.json() == {"detail": "Not found"}
    assert foreign_result.json() == unknown_result.json() == {"detail": "Not found"}
    assert foreign_delete.json() == unknown_delete.json() == {"detail": "Not found"}
    for response in (foreign_status, foreign_result, foreign_delete):
        assert "Welcome" not in response.text
        assert "Agenda" not in response.text
        assert "Fixture text" not in response.text
        assert job_id not in response.text
    holder["tenant"] = "tenant-a"
    owner = client.get(f"{JOBS}/{job_id}/result")
    assert owner.status_code == 200
    assert "Welcome to the synthetic planning standup." in owner.text


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://fixtures.nova.invalid/synthetic/meeting-clip-01",
        "https://user:pass@fixtures.nova.invalid/synthetic/meeting-clip-01",
        "https://localhost/synthetic/meeting-clip-01",
        "https://127.0.0.1/latest",
        "https://[::1]/",
        "https://10.1.2.3/clip",
        "https://192.168.1.20/clip",
        "https://172.16.0.5/clip",
        "https://169.254.169.254/latest/meta-data/",
        "https://169.254.1.1/link-local",
        "https://[fe80::1]/",
        "https://2130706433/",
        "https://0177.0.0.1/",
        "https://0x7f.0.0.1/",
        "https://[::ffff:169.254.169.254]/",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://evil.example/redirect",
        "https://example.com/video.mp4?redirect=http://169.254.169.254",
        "https://fixtures.nova.invalid/synthetic/meeting-clip-01?next=http://127.0.0.1",
        "https://fixtures.nova.invalid/synthetic/meeting-clip-01/../../etc/passwd",
        "https://fixtures.nova.invalid/synthetic/%2e%2e/%2e%2e/etc/passwd",
        "https://example.com/video.mp4",
        "https://8.8.8.8/clip.mp4",
    ],
)
def test_ssrf_and_unknown_urls_fail_closed(monkeypatch, no_network, url):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    with pytest.raises(UnsafeMediaUrl):
        if url in {
            "https://example.com/video.mp4",
        }:
            validate_https_url(url)
            resolve_allowlisted_fixture(url)
        else:
            validate_https_url(url)
    client = _client()
    response = client.post(JOBS, json=_payload("https_url", url))
    assert response.status_code == 400
    assert response.json() == {"detail": "Source is not allowed"}
    assert url not in response.text
    assert "169.254.169.254" not in response.text
    assert "passwd" not in response.text


def test_allowlisted_url_does_not_use_the_network(monkeypatch, no_network):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    assert resolve_allowlisted_fixture(ALLOWLIST_URL) == "meeting-clip-01"
    client = _client()
    response = client.post(JOBS, json=_payload("https_url", ALLOWLIST_URL))
    assert response.status_code == 201
    assert response.json()["status"] == "completed"


@pytest.mark.parametrize(
    ("source_type", "value"),
    [
        ("fixture", "../etc/passwd"),
        ("fixture", "..%2f..%2fetc/passwd"),
        ("fixture", "meeting-clip-01/../../secret"),
        ("upload", "/var/tmp/../secret.mp4"),
        ("upload_id", "../../etc/passwd"),
        ("file", "file:///etc/passwd"),
        ("path", "..\\windows\\system32"),
        ("fixture", "not-a-real-clip"),
    ],
)
def test_path_traversal_and_upload_sources_are_rejected(monkeypatch, no_network, source_type, value):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    client = _client()
    response = client.post(JOBS, json=_payload(source_type, value))
    assert response.status_code == 400
    assert response.json() == {"detail": "Source is not allowed"}
    assert "passwd" not in response.text
    assert "system32" not in response.text
    follow = client.get(f"{JOBS}/{UNKNOWN_JOB}")
    assert follow.status_code == 404


def test_extra_path_field_is_rejected(monkeypatch):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    client = _client()
    body = _payload()
    body["source"]["path"] = "../../etc/passwd"
    response = client.post(JOBS, json=body)
    assert response.status_code == 422
    assert "Welcome" not in response.text


def test_audit_log_stores_ids_only(monkeypatch, caplog):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    caplog.set_level("INFO")
    client = _client()
    created = client.post(JOBS, json=_payload())
    job_id = created.json()["job_id"]
    deleted = client.delete(f"{JOBS}/{job_id}")
    assert deleted.status_code == 200
    text = caplog.text
    assert job_id in text
    assert "tenant-a" in text
    assert "meeting-clip-01" in text
    assert "completed" in text
    assert "erased" in text
    assert "Welcome" not in text
    assert "Agenda" not in text
    assert "audio:1-3" not in text
    assert "frame:8" not in text
    assert "Fixture text" not in text


def test_rejected_url_is_not_audited(monkeypatch, caplog):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    caplog.set_level("INFO")
    client = _client()
    response = client.post(
        JOBS,
        json=_payload("https_url", "https://169.254.169.254/latest/meta-data/"),
    )
    assert response.status_code == 400
    assert "169.254.169.254" not in caplog.text
    assert "media_job job_id=" not in caplog.text


def test_main_wires_one_guarded_include():
    text = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    assert text.count("from app.core.nova.intelligence.router import router as nova_intelligence_media_router") == 1
    assert text.count("app.include_router(nova_intelligence_media_router)") == 1
    assert "NOVA_INTELLIGENCE_MEDIA" in text


def test_slice_sources_do_not_reference_providers():
    root = Path(__file__).resolve().parents[1] / "app" / "core" / "nova" / "intelligence"
    banned = (
        "creative_studio",
        "import socket",
        "urlopen",
        "openai",
        "stripe",
        "ffmpeg",
        "tesseract",
    )
    for path in root.rglob("*.py"):
        if path.name == "operational_engine.py":
            continue
        text = path.read_text().lower()
        for word in banned:
            assert word not in text, path.name
