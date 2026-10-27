"""Job behavior for offline synthetic media evidence."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.intelligence.demo import render_demo_page
from app.core.nova.intelligence.fixtures import FIXTURES
from app.core.nova.intelligence.jobs import reset_jobs
from app.core.nova.intelligence.messages import (
    DIARIZATION_NOT_PERFORMED,
    NOTHING_INVENTED,
    NOT_PRODUCTION,
    SPEAKERS_UNKNOWN,
    SUMMARY_IS_FIXTURE,
)
from app.core.nova.intelligence.quotas import MAX_DECLARED_BYTES
from app.core.nova.intelligence.router import router
from app.core.nova.intelligence.timeline import timeline

JOBS = "/api/nova/intelligence/media/jobs"
DEMO = "/nova/intelligence/media-demo"
ALLOWLIST_URL = "https://fixtures.nova.invalid/synthetic/meeting-clip-01"


@pytest.fixture(autouse=True)
def _isolate():
    reset_jobs()
    yield
    reset_jobs()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NOVA_INTELLIGENCE_MEDIA", "1")
    app = FastAPI()
    app.include_router(router)
    holder = {"tenant": "tenant-a"}

    def _current():
        tenant_id = holder["tenant"]
        return UserContext(
            user_id=f"user-{tenant_id}",
            email=f"{tenant_id}@example.invalid",
            role="staff",
            organization_id=tenant_id,
        )

    app.dependency_overrides[get_current_user_context] = _current
    return TestClient(app), holder


def _payload(source_type: str = "fixture", value: str = "meeting-clip-01", **overrides) -> dict:
    body = {
        "source": {"type": source_type, "value": value},
        "media_type": "video/mp4",
        "declared_bytes": 2048,
    }
    body.update(overrides)
    return body


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def test_fixture_job_returns_time_ordered_source_evidence(client):
    http, _holder = client
    created = http.post(JOBS, json=_payload())
    assert created.status_code == 201
    job_id = created.json()["job_id"]
    assert created.json()["status"] == "completed"
    status = http.get(f"{JOBS}/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["progress"] == 1.0
    assert "Welcome" not in status.text
    result = http.get(f"{JOBS}/{job_id}/result")
    assert result.status_code == 200
    body = result.json()
    expected = timeline(FIXTURES["meeting-clip-01"].observations)
    assert FIXTURES["meeting-clip-01"].observations[0].source_ref == "frame:8"
    assert body["observations"] == expected
    assert [row["source_ref"] for row in body["observations"]] == [
        "audio:1-3",
        "audio:4-7",
        "frame:8",
        "frame:8-12",
    ]
    assert body["transcript_segments"][0]["source_ref"] == "audio:1-3"
    assert body["frame_observations"][0]["source_ref"] == "frame:8"
    assert body["summary"].startswith("Fixture text:")
    assert body["synthetic"] is True
    assert body["production_analysis"] is False
    assert SPEAKERS_UNKNOWN in body["warnings"]
    assert SUMMARY_IS_FIXTURE in body["warnings"]
    assert DIARIZATION_NOT_PERFORMED in body["warnings"]
    assert all("speaker" not in key.lower() for key in _keys(body))


def test_allowlisted_https_url_uses_the_same_fixture(client):
    http, _holder = client
    created = http.post(JOBS, json=_payload("https_url", ALLOWLIST_URL))
    assert created.status_code == 201
    result = http.get(f"{JOBS}/{created.json()['job_id']}/result")
    assert [row["source_ref"] for row in result.json()["observations"]][0] == "audio:1-3"


def test_diarization_request_does_not_name_a_person(client):
    http, _holder = client
    created = http.post(
        JOBS,
        json=_payload(options={"diarize": True, "speaker_name": "Alice"}),
    )
    result = http.get(f"{JOBS}/{created.json()['job_id']}/result")
    assert result.status_code == 200
    assert "Alice" not in result.text
    assert DIARIZATION_NOT_PERFORMED in result.json()["warnings"]
    assert all("speaker" not in key.lower() for key in _keys(result.json()))


def test_empty_and_failed_jobs_do_not_invent_observations(client):
    http, _holder = client
    empty = http.post(JOBS, json=_payload(value="meeting-clip-empty"))
    empty_body = http.get(f"{JOBS}/{empty.json()['job_id']}/result").json()
    assert empty_body["status"] == "completed"
    assert empty_body["observations"] == []
    assert empty_body["transcript_segments"] == []
    assert empty_body["frame_observations"] == []
    assert empty_body["scenes"] == []
    assert empty_body["summary"] is None
    assert empty_body["observations"] == timeline([])
    assert NOTHING_INVENTED in empty_body["warnings"]
    failed = http.post(JOBS, json=_payload(value="meeting-clip-failed"))
    assert failed.json()["status"] == "failed"
    failed_status = http.get(f"{JOBS}/{failed.json()['job_id']}")
    assert failed_status.json()["error_code"] == "no_evidence"
    failed_body = http.get(f"{JOBS}/{failed.json()['job_id']}/result").json()
    assert failed_body["status"] == "failed"
    assert failed_body["observations"] == []
    assert failed_body["summary"] is None
    assert failed_body["duration_seconds"] is None
    assert "Welcome" not in str(failed_body)
    assert "Agenda" not in str(failed_body)
    assert NOTHING_INVENTED in failed_body["warnings"]


@pytest.mark.parametrize(
    ("media_type", "declared_bytes", "detail"),
    [
        ("text/html", 1024, "Media type is not allowed"),
        ("video/webm", 1024, "Media type is not allowed"),
        ("video/mp4", 0, "Declared size exceeds quota"),
        ("video/mp4", -5, "Declared size exceeds quota"),
        ("video/mp4", MAX_DECLARED_BYTES + 1, "Declared size exceeds quota"),
    ],
)
def test_quota_rejections(client, media_type, declared_bytes, detail):
    http, _holder = client
    response = http.post(
        JOBS,
        json=_payload(media_type=media_type, declared_bytes=declared_bytes),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == detail


def test_declared_size_at_the_quota_is_accepted(client):
    http, _holder = client
    response = http.post(JOBS, json=_payload(declared_bytes=MAX_DECLARED_BYTES))
    assert response.status_code == 201


def test_delete_erases_the_job_for_that_tenant(client):
    http, holder = client
    created = http.post(JOBS, json=_payload())
    job_id = created.json()["job_id"]
    holder["tenant"] = "tenant-b"
    assert http.delete(f"{JOBS}/{job_id}").status_code == 404
    holder["tenant"] = "tenant-a"
    assert "Welcome" in http.get(f"{JOBS}/{job_id}/result").text
    deleted = http.delete(f"{JOBS}/{job_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"job_id": job_id, "status": "erased"}
    assert "Welcome" not in deleted.text
    assert "Agenda" not in deleted.text
    missing = http.get(f"{JOBS}/{job_id}")
    missing_result = http.get(f"{JOBS}/{job_id}/result")
    unknown = http.get(f"{JOBS}/00000000-0000-4000-8000-000000000099")
    assert missing.status_code == 404
    assert missing.json() == unknown.json() == {"detail": "Not found"}
    assert missing_result.json() == {"detail": "Not found"}
    assert http.delete(f"{JOBS}/{job_id}").status_code == 404


def test_demo_page_shows_synthetic_timeline(client):
    http, _holder = client
    response = http.get(DEMO)
    assert response.status_code == 200
    html = response.text
    assert "Synthetic fixture." in html
    assert NOT_PRODUCTION in html
    assert SPEAKERS_UNKNOWN in html
    assert "audio:1-3" in html
    assert "frame:8" in html
    assert html.index("audio:1-3") < html.index("frame:8")
    assert "1.0" in html
    assert "8.0" in html
    lowered = html.lower()
    assert "<script" not in lowered
    assert "innerhtml" not in lowered
    assert "https:" not in lowered
    assert "http:" not in lowered
    assert "src=" not in lowered


def test_demo_escapes_fixture_text():
    html = render_demo_page(
        observations=[
            {
                "start_seconds": 1.0,
                "end_seconds": 3.0,
                "kind": "transcript",
                "text": "<script>alert(1)</script>",
                "source_ref": "audio:1-3",
            }
        ],
        summary="Fixture text only",
    )
    assert "<script" not in html.lower()
    assert "&lt;script&gt;" in html
    assert "innerHTML" not in html


def test_operational_engine_import_path_still_works():
    from app.core.nova.intelligence import NovaIntelligenceEngine

    assert NovaIntelligenceEngine.__name__ == "NovaIntelligenceEngine"
