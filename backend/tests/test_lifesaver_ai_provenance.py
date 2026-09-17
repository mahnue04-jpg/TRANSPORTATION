"""Source-grounded AI summaries. No diagnosis and no invented measurements."""
from __future__ import annotations

import os
from datetime import timedelta

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.helpers import now
from app.main import app
from app.modules.lifesaver.ai_provenance import refuses_diagnosis_wording, summarize_from_records
from app.modules.lifesaver.models import ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, create_other_org_user, grant_consents


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def _ready(client: TestClient) -> dict[str, str]:
    headers = auth_headers(client, "rider@amicor.local")
    grant_consents(client, headers)
    bootstrap_profile(client, headers)
    return headers


def test_unit_no_source_and_disclosures():
    empty = summarize_from_records([])
    assert empty["mode"] == "provenance_no_source"
    assert "no trustworthy reading" in empty["reply"].lower()
    assert empty["provenance"]["missing_data_flags"] == ["no_source"]

    stale = summarize_from_records(
        [
            {
                "id": "stale-1",
                "provenance_id": "stale-1",
                "measurement_type": "weight",
                "value": 182,
                "unit": "lb",
                "captured_at": now().isoformat(),
                "quality_status": "STALE",
                "trusted": False,
                "simulated": True,
            }
        ]
    )
    assert stale["mode"] == "provenance_all_stale"
    assert "stale" in stale["reply"].lower()

    invalid = summarize_from_records(
        [
            {
                "id": "bad-1",
                "provenance_id": "bad-1",
                "measurement_type": "weight",
                "value": 5000,
                "unit": "lb",
                "quality_status": "INVALID",
                "trusted": False,
                "simulated": True,
            }
        ]
    )
    assert invalid["mode"] == "provenance_all_rejected"

    mixed = summarize_from_records(
        [
            {
                "id": "ok-1",
                "provenance_id": "ok-1",
                "measurement_type": "weight",
                "value": 182,
                "unit": "lb",
                "captured_at": now().isoformat(),
                "quality_status": "VALID",
                "trusted": True,
                "simulated": True,
                "source_type": "simulated",
            },
            {
                "id": "bad-2",
                "provenance_id": "bad-2",
                "measurement_type": "weight",
                "value": 10,
                "unit": "lb",
                "quality_status": "INVALID",
                "trusted": False,
                "simulated": True,
            },
        ]
    )
    assert mixed["mode"] == "provenance_summary"
    assert "182" in mixed["reply"]
    assert "ok-1" in mixed["reply"]
    assert "bad-2" in mixed["reply"]
    assert mixed["provenance"]["trusted_record_count"] == 1
    assert "bad-2" in mixed["provenance"]["rejected_record_ids"]
    assert refuses_diagnosis_wording(mixed["reply"])


def test_unit_manual_and_simulated_wording():
    manual = summarize_from_records(
        [
            {
                "id": "man-1",
                "provenance_id": "man-1",
                "measurement_type": "weight",
                "value": 182,
                "unit": "lb",
                "captured_at": now().isoformat(),
                "quality_status": "VALID",
                "trusted": True,
                "simulated": False,
                "source": "user_entered",
                "source_type": "manual_entry",
            }
        ]
    )
    assert "manual" in manual["reply"].lower()
    assert "no prior trustworthy weight reading" in manual["reply"].lower()
    assert refuses_diagnosis_wording(manual["reply"])


def _ask(client: TestClient, headers: dict[str, str], message: str) -> dict:
    response = client.post("/api/lifesaver/ai/converse", headers=headers, json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_converse_provenance_paths():
    client = _client()
    create_other_org_user("lifesaver.provenance.empty@example.local")
    empty_headers = auth_headers(client, "lifesaver.provenance.empty@example.local")
    grant_consents(client, empty_headers)
    bootstrap_profile(client, empty_headers)
    none = _ask(client, empty_headers, "Summarize my weight reading")
    create_other_org_user("lifesaver.provenance.main@example.local")
    headers = auth_headers(client, "lifesaver.provenance.main@example.local")
    grant_consents(client, headers)
    bootstrap_profile(client, headers)
    assert none["mode"] == "provenance_no_source"
    assert none["uses_nova_engine"] is False
    assert "no trustworthy reading" in none["reply"].lower()
    assert none["provenance"]["trusted_record_count"] == 0

    current = now()
    simulated = client.post(
        "/api/lifesaver/readings",
        headers=headers,
        json={
            "reading_type": "weight",
            "value_primary": 182,
            "source": "simulated",
            "captured_at": current.isoformat(),
        },
    ).json()["data"]
    sim_reply = _ask(client, headers, "Summarize my weight reading")
    assert sim_reply["mode"] == "provenance_summary"
    assert "182" in sim_reply["reply"]
    assert "simulated" in sim_reply["reply"].lower()
    assert simulated["id"] in sim_reply["reply"]
    assert simulated["id"] in sim_reply["provenance"]["source_record_ids"]
    assert sim_reply["provenance"]["simulated_sources_present"] is True
    assert refuses_diagnosis_wording(sim_reply["reply"])
    assert "dangerous" not in sim_reply["reply"].lower().replace("cannot diagnose", "")

    manual = client.post(
        "/api/lifesaver/readings",
        headers=headers,
        json={
            "reading_type": "glucose",
            "value_primary": 102,
            "source": "user_entered",
            "captured_at": current.isoformat(),
        },
    ).json()["data"]
    man_reply = _ask(client, headers, "Summarize my glucose measurement")
    assert "manual" in man_reply["reply"].lower()
    assert manual["id"] in man_reply["provenance"]["source_record_ids"]

    create_other_org_user("lifesaver.provenance.stale@example.local")
    stale_only_headers = auth_headers(client, "lifesaver.provenance.stale@example.local")
    grant_consents(client, stale_only_headers)
    bootstrap_profile(client, stale_only_headers)
    client.post(
        "/api/lifesaver/readings",
        headers=stale_only_headers,
        json={
            "reading_type": "weight",
            "value_primary": 190,
            "source": "simulated",
            "captured_at": (current - timedelta(hours=40)).isoformat(),
        },
    )
    stale_reply = _ask(client, stale_only_headers, "Summarize my weight reading")
    assert stale_reply["mode"] == "provenance_all_stale"

    create_other_org_user("lifesaver.provenance.invalid@example.local")
    invalid_headers = auth_headers(client, "lifesaver.provenance.invalid@example.local")
    grant_consents(client, invalid_headers)
    bootstrap_profile(client, invalid_headers)
    client.post(
        "/api/lifesaver/readings",
        headers=invalid_headers,
        json={"reading_type": "weight", "value_primary": 5000, "source": "simulated"},
    )
    invalid_reply = _ask(client, invalid_headers, "Summarize my weight reading")
    assert invalid_reply["mode"] == "provenance_all_rejected"

    mixed = _ask(client, headers, "Summarize my readings")
    assert mixed["mode"] == "provenance_summary"
    assert mixed["provenance"]["trusted_record_count"] >= 1
    assert refuses_diagnosis_wording(mixed["reply"])
