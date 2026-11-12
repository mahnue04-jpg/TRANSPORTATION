"""Stay360 API contracts, locale catalogs, and dashboard structure."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from stay360_support import anonymous_client, assert_clean, client_for, reset_stay360_store, user
from stay360_support import HARBOR_TENANT

from app.core.nova.stay360.constants import (
    BLUEPRINT_NOTE,
    BLUEPRINT_TITLE,
    BLUEPRINT_VERSION,
    DESCRIPTOR,
    DOCUMENT_TITLE,
    PRODUCT_NAME,
)
from app.core.nova.stay360.errors import Stay360ProviderBlocked, reject_external_provider
from app.core.nova.stay360.fixtures import assert_synthetic_fixtures, public_guest_labels, sensitive_corpus
from app.core.nova.stay360.locales import CATALOGS, locale_keys
from app.core.nova.stay360.schemas import MobileCheckInResult, ReservationView
from app.core.nova.stay360.service import Stay360Service

PACKAGE = Path(__file__).resolve().parents[1] / "app" / "core" / "nova" / "stay360"
STATIC = Path(__file__).resolve().parents[1] / "static" / "nova-stay360"
MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"
BANNED_IMPORTS = {"requests", "httpx", "urllib", "socket", "stripe", "aiohttp", "openai", "http"}


@pytest.fixture(autouse=True)
def _reset():
    reset_stay360_store()
    yield
    reset_stay360_store()


def test_fixtures_are_synthetic_and_labels_are_not_secrets():
    assert_synthetic_fixtures()
    corpus = sensitive_corpus()
    assert len(corpus) >= 9
    for label in public_guest_labels():
        assert label not in corpus
        assert "@" not in label


def test_locale_catalogs_share_keys_and_keep_the_product_name():
    expected = locale_keys()
    assert "product.name" in expected
    assert "slice.scope_note" in expected
    for code, catalog in CATALOGS.items():
        assert set(catalog) == set(expected)
        assert catalog["product.name"] == PRODUCT_NAME
        assert BLUEPRINT_NOTE in catalog["slice.scope_note"]
        assert "parking" in catalog["slice.scope_note"]
        assert "itinerary" in catalog["slice.scope_note"]
    assert CATALOGS["en"]["product.descriptor"] == DESCRIPTOR


def test_slice_note_records_the_missing_blueprint():
    note = (PACKAGE / "SLICE.md").read_text(encoding="utf-8")
    coverage = (PACKAGE / "BLUEPRINT_COVERAGE.md").read_text(encoding="utf-8")
    assert PRODUCT_NAME in note
    assert DESCRIPTOR in note
    assert BLUEPRINT_NOTE in note
    assert "Those titles are different." in note
    assert DOCUMENT_TITLE in note
    assert "Not implemented" in coverage
    assert "Section titles are not in the repository" in coverage
    for section in (
        "Hotel guest and reservation data model",
        "Parking",
        "Concierge",
        "Guest services",
        "Room inventory safeguards",
        "Family and events",
        "Marketing",
        "Itinerary",
    ):
        assert section in coverage
    assert "nine of the 26" in coverage
    for section in (
        "parking",
        "concierge",
        "guest services",
        "inventory safeguards",
        "family/events",
        "marketing",
        "itinerary",
    ):
        assert section in note


def test_package_does_not_import_network_or_payment_clients():
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            assert BANNED_IMPORTS.isdisjoint(names), path.name
    with pytest.raises(Stay360ProviderBlocked):
        reject_external_provider("fixture-air")
    assert Stay360Service.provider_calls == 0


def test_public_meta_locales_and_page_contract():
    client = anonymous_client()
    meta = client.get("/api/nova/stay360/meta")
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert body["product_name"] == PRODUCT_NAME
    assert body["descriptor"] == DESCRIPTOR
    assert body["document_title"] == DOCUMENT_TITLE
    assert body["blueprint_title"] == BLUEPRINT_TITLE
    assert body["blueprint_version"] == BLUEPRINT_VERSION
    assert body["blueprint_section_count"] == 26
    assert body["blueprint_source_in_repo"] is False
    assert body["product_name"] != body["blueprint_title"]
    assert body["blueprint_title"] not in body["document_title"]
    assert body["blueprint_version"] not in body["document_title"]
    assert body["synthetic_only"] is True
    assert body["network_providers"] == "disabled"
    assert body["payment_capture"] is False
    assert body["physical_access_control"] is False
    assert body["door_access"] == "not_issued"
    assert body["blueprint_note"] == BLUEPRINT_NOTE
    assert body["not_implemented"] == [
        "parking",
        "concierge",
        "guest_services",
        "inventory_safeguards",
        "family_events",
        "marketing",
        "itinerary",
    ]
    assert_clean(body)

    locales = client.get("/api/nova/stay360/locales")
    assert locales.status_code == 200
    assert locales.json()["locales"] == ["en", "es", "fr"]
    english = client.get("/api/nova/stay360/locales/en")
    assert english.status_code == 200
    assert english.json()["strings"]["product.descriptor"] == DESCRIPTOR
    assert client.get("/api/nova/stay360/locales/de").status_code == 404
    assert_clean(english.json())

    page = client.get("/nova/stay360")
    assert page.status_code == 200
    html = page.text
    assert PRODUCT_NAME in html
    assert DESCRIPTOR in html
    title = html.split("<title>", 1)[1].split("</title>", 1)[0]
    assert title == DOCUMENT_TITLE
    assert BLUEPRINT_TITLE not in title
    assert "Hospitality &amp; Travel Master Blueprint, version 1.1. This is not the product title." in html
    assert "Those titles are different." in html
    assert 'src="/static/nova-stay360/stay360.js"' in html
    keys = set()
    for part in html.split('data-i18n="')[1:]:
        keys.add(part.split('"', 1)[0])
    assert keys <= set(locale_keys())
    script = (STATIC / "stay360.js").read_text(encoding="utf-8")
    style = (STATIC / "stay360.css").read_text(encoding="utf-8")
    for source in (html, script, style):
        assert "https://" not in source
        assert "http://" not in source
        assert "innerHTML" not in source
    assert 'text("dashboard.rooms_not_ready"), counts.rooms_not_ready' in script
    assert 'text("readiness.not_ready"), counts.rooms_not_ready' not in script
    assert 'document.title = product + " \\u2014 " + descriptor' in script
    assert "/api/nova/stay360/dashboard" in script
    assert "/api/nova/stay360/arrivals/refresh" in script
    assert "mobile-check-in" in script


def test_openapi_lists_the_slice_routes_and_rejects_secret_fields():
    client = anonymous_client()
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = set(schema.json()["paths"])
    expected = {
        "/api/nova/stay360/meta",
        "/api/nova/stay360/locales",
        "/api/nova/stay360/locales/{code}",
        "/api/nova/stay360/dashboard",
        "/api/nova/stay360/reservations",
        "/api/nova/stay360/reservations/{reference}",
        "/api/nova/stay360/prearrival",
        "/api/nova/stay360/arrivals/refresh",
        "/api/nova/stay360/rooms",
        "/api/nova/stay360/rooms/{room_number}/housekeeping",
        "/api/nova/stay360/reservations/{reference}/mobile-check-in",
    }
    assert expected <= paths
    with pytest.raises(ValidationError):
        ReservationView.model_validate(
            {
                "reservation_reference": "STAY-HLI-1001",
                "guest_label": "A. Lane",
                "room_number": "214",
                "arrival_date": "2026-10-26",
                "departure_date": "2026-10-28",
                "arrival_mode": "flight",
                "arrival_status": "scheduled",
                "arrival_detail": "Fixture Air LN441 is scheduled",
                "eta_local": "16:10",
                "housekeeping_status": "dirty",
                "room_readiness": "not_ready",
                "check_in_eligibility": "ineligible",
                "check_in_blockers": ["room_not_ready"],
                "check_in_status": "not_checked_in",
                "legal_name": "Avery Quinn Lane",
            }
        )
    with pytest.raises(ValidationError):
        MobileCheckInResult.model_validate(
            {
                "reservation_reference": "STAY-HLI-1008",
                "outcome": "simulated",
                "check_in_status": "simulated_checked_in",
                "room_number": "118",
                "door_access": "not_issued",
                "physical_access_control": False,
                "payment_captured": False,
                "confirmation_code": "SIM-STAY-HLI-1008",
                "door_code": "1357",
            }
        )


def test_main_wires_stay360_without_removing_other_nova_routers():
    text = MAIN.read_text(encoding="utf-8")
    assert "from app.core.nova.stay360.router import router as nova_stay360_router" in text
    assert "app.include_router(nova_stay360_router)" in text
    for name in (
        "nova_creative_router",
        "nova_casting_router",
        "nova_work_router",
        "nova_freight_router",
        "nova_language_router",
    ):
        assert f"app.include_router({name})" in text


def test_staff_list_matches_the_reservation_contract():
    staff = user("staff-harbor", "staff", HARBOR_TENANT)
    response = client_for(staff).get("/api/nova/stay360/reservations")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["synthetic"] is True
    assert body["reservations"]
    for row in body["reservations"]:
        ReservationView.model_validate(row)
        assert set(row) == set(ReservationView.model_fields)
    assert_clean(body, staff.email)
