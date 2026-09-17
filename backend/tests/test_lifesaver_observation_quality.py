"""Observation-quality protections for simulated and manual ingest."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.helpers import now
from app.main import app
from app.modules.lifesaver.models import ensure_lifesaver_schema
from app.modules.lifesaver.observation_quality import (
    QUALITY_DUPLICATE,
    QUALITY_INVALID,
    QUALITY_MISSING,
    QUALITY_OUT_OF_ORDER,
    QUALITY_STALE,
    QUALITY_UNSUPPORTED,
    QUALITY_VALID,
    assess,
)
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, grant_consents


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


def test_unit_valid_reading():
    result = assess(measurement_type="weight", value=182, unit="lb", source="simulated")
    assert result.quality_status == QUALITY_VALID
    assert result.trusted is True
    assert result.simulated is True
    assert result.would_alert is True


def test_unit_duplicate_and_same_value_new_timestamp():
    captured = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    first = assess(
        measurement_type="weight",
        value=182,
        unit="lb",
        source="simulated",
        captured_at=captured,
    )
    duplicate = assess(
        measurement_type="weight",
        value=182,
        unit="lb",
        source="simulated",
        captured_at=captured,
        prior_fingerprints=[first.fingerprint],
    )
    assert duplicate.quality_status == QUALITY_DUPLICATE
    assert duplicate.trusted is False
    assert duplicate.would_alert is False
    newer = assess(
        measurement_type="weight",
        value=182,
        unit="lb",
        source="simulated",
        captured_at=captured + timedelta(hours=1),
        prior_fingerprints=[first.fingerprint],
        latest_captured_at=captured,
    )
    assert newer.quality_status == QUALITY_VALID


def test_unit_stale_future_missing_unsupported_invalid_out_of_order():
    current = now()
    stale = assess(
        measurement_type="glucose",
        value=110,
        unit="mg/dL",
        source="user_entered",
        captured_at=current - timedelta(hours=30),
        received_at=current,
    )
    assert stale.quality_status == QUALITY_STALE
    future = assess(
        measurement_type="glucose",
        value=110,
        unit="mg/dL",
        source="user_entered",
        captured_at=current + timedelta(hours=2),
        received_at=current,
    )
    assert future.quality_status == QUALITY_INVALID
    missing_unit = assess(
        measurement_type="weight",
        value=182,
        source="simulated",
        unit_explicitly_missing=True,
    )
    assert missing_unit.quality_status == QUALITY_MISSING
    unsupported_type = assess(measurement_type="brainwave", value=1, unit="hz", source="simulated")
    assert unsupported_type.quality_status == QUALITY_UNSUPPORTED
    unsupported_source = assess(measurement_type="weight", value=182, unit="lb", source="real_cgm")
    assert unsupported_source.quality_status == QUALITY_UNSUPPORTED
    invalid = assess(measurement_type="weight", value=5000, unit="lb", source="simulated")
    assert invalid.quality_status == QUALITY_INVALID
    not_number = assess(measurement_type="weight", value="not-a-number", unit="lb", source="simulated")
    assert not_number.quality_status == QUALITY_INVALID
    out_of_order = assess(
        measurement_type="weight",
        value=180,
        unit="lb",
        source="simulated",
        captured_at=current - timedelta(minutes=10),
        received_at=current,
        latest_captured_at=current,
    )
    assert out_of_order.quality_status == QUALITY_OUT_OF_ORDER


def _post_reading(client: TestClient, headers: dict[str, str], **body):
    response = client.post("/api/lifesaver/readings", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_manual_and_connected_quality_ingest():
    client = _client()
    headers = _ready(client)
    current = now()
    valid = _post_reading(
        client,
        headers,
        reading_type="weight",
        value_primary=182,
        source="simulated",
        captured_at=current.isoformat(),
    )
    assert valid["quality_status"] == QUALITY_VALID
    assert valid["trusted"] is True
    assert valid["simulated"] is True
    assert valid["provenance_id"]

    duplicate = _post_reading(
        client,
        headers,
        reading_type="weight",
        value_primary=182,
        source="simulated",
        captured_at=current.isoformat(),
    )
    assert duplicate["quality_status"] == QUALITY_DUPLICATE
    assert duplicate["trusted"] is False
    assert duplicate["ingestion_status"] == "stored_untrusted"

    same_value = _post_reading(
        client,
        headers,
        reading_type="weight",
        value_primary=182,
        source="simulated",
        captured_at=(current + timedelta(minutes=5)).isoformat(),
    )
    assert same_value["quality_status"] == QUALITY_VALID

    stale = _post_reading(
        client,
        headers,
        reading_type="glucose",
        value_primary=110,
        source="user_entered",
        captured_at=(current - timedelta(hours=30)).isoformat(),
    )
    assert stale["quality_status"] == QUALITY_STALE
    assert stale["trusted"] is False

    future = _post_reading(
        client,
        headers,
        reading_type="glucose",
        value_primary=111,
        source="user_entered",
        captured_at=(current + timedelta(hours=3)).isoformat(),
    )
    assert future["quality_status"] == QUALITY_INVALID

    missing_unit = _post_reading(
        client,
        headers,
        reading_type="temperature",
        value_primary=98.6,
        source="simulated",
        unit="",
    )
    assert missing_unit["quality_status"] == QUALITY_MISSING

    invalid = _post_reading(
        client,
        headers,
        reading_type="weight",
        value_primary=5000,
        source="simulated",
    )
    assert invalid["quality_status"] == QUALITY_INVALID

    out_of_order = _post_reading(
        client,
        headers,
        reading_type="weight",
        value_primary=170,
        source="simulated",
        captured_at=(current - timedelta(minutes=1)).isoformat(),
    )
    assert out_of_order["quality_status"] == QUALITY_OUT_OF_ORDER

    device = client.post(
        "/api/lifesaver/connected-health/devices",
        headers=headers,
        json={"device_type": "weight_scale"},
    ).json()["data"]
    unsupported_type = client.post(
        f"/api/lifesaver/connected-health/devices/{device['id']}/readings",
        headers=headers,
        json={"reading_kind": "brainwave", "value_primary": 1, "unit": "hz"},
    )
    assert unsupported_type.status_code == 200, unsupported_type.text
    assert unsupported_type.json()["data"]["quality_status"] == QUALITY_UNSUPPORTED
    assert unsupported_type.json()["data"]["trusted"] is False

    unsupported_source = client.post(
        f"/api/lifesaver/connected-health/devices/{device['id']}/readings",
        headers=headers,
        json={"reading_kind": "weight", "value_primary": 180, "unit": "lb", "source": "real_cgm"},
    )
    assert unsupported_source.status_code == 200, unsupported_source.text
    assert unsupported_source.json()["data"]["quality_status"] == QUALITY_UNSUPPORTED

    stale_flagged = client.post(
        f"/api/lifesaver/connected-health/devices/{device['id']}/readings",
        headers=headers,
        json={
            "reading_kind": "weight",
            "value_primary": 181,
            "unit": "lb",
            "flag_for_review": True,
            "captured_at": (current - timedelta(hours=36)).isoformat(),
        },
    ).json()["data"]
    assert stale_flagged["quality_status"] == QUALITY_STALE
    assert stale_flagged["review_status"] == "none"
    assert stale_flagged["human_review_required"] is False
