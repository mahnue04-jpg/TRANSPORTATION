"""Stay360 tenant, role, and privacy security tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from stay360_support import (
    CEDAR_TENANT,
    HARBOR_TENANT,
    anonymous_client,
    assert_clean,
    client_for,
    reset_stay360_store,
    user,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_stay360_store()
    yield
    reset_stay360_store()


def test_staff_cannot_read_another_hotel_or_search_by_raw_identity():
    harbor = user("staff-harbor", "staff", HARBOR_TENANT)
    cedar = user("staff-cedar", "staff", CEDAR_TENANT)
    harbor_client = client_for(harbor)
    cedar_client = client_for(cedar)

    harbor_list = harbor_client.get("/api/nova/stay360/reservations")
    cedar_list = cedar_client.get("/api/nova/stay360/reservations")
    assert harbor_list.status_code == 200
    assert cedar_list.status_code == 200
    harbor_refs = {row["reservation_reference"] for row in harbor_list.json()["reservations"]}
    cedar_refs = {row["reservation_reference"] for row in cedar_list.json()["reservations"]}
    assert "STAY-CRH-2001" not in harbor_refs
    assert "STAY-HLI-1001" not in cedar_refs
    assert "C. Reed" not in harbor_list.text
    assert "A. Lane" not in cedar_list.text
    assert_clean(harbor_list.json(), harbor.email)
    assert_clean(cedar_list.json(), cedar.email)

    hidden = harbor_client.get("/api/nova/stay360/reservations/STAY-CRH-2001")
    missing = harbor_client.get("/api/nova/stay360/reservations/STAY-HLI-9999")
    assert hidden.status_code == 404
    assert missing.status_code == 404
    assert hidden.json()["detail"] == missing.json()["detail"]
    assert "Casey Rowan Reed" not in hidden.text
    assert "C. Reed" not in hidden.text
    assert_clean(hidden.json(), harbor.email)

    filtered = harbor_client.get("/api/nova/stay360/reservations", params={"reservation_reference": "STAY-CRH-2001"})
    assert filtered.status_code == 200
    assert filtered.json()["reservations"] == []
    assert_clean(filtered.json(), harbor.email)

    probed = harbor_client.get(
        "/api/nova/stay360/reservations",
        params={"email": "guest-casey@example.invalid"},
    )
    assert probed.status_code == 422
    assert probed.json()["detail"]["code"] == "sensitive_lookup_rejected"
    assert "guest-casey@example.invalid" not in probed.text
    named = harbor_client.get("/api/nova/stay360/dashboard", params={"legal_name": "Casey Rowan Reed"})
    assert named.status_code == 422
    assert "Casey Rowan Reed" not in named.text


def test_admin_role_does_not_cross_tenants_and_guests_stay_on_their_reservation():
    admin = client_for(user("admin-cedar", "admin", CEDAR_TENANT))
    support = client_for(user("support-cedar", "super_admin_support", CEDAR_TENANT))
    avery = user("guest-avery", "rider", HARBOR_TENANT)
    avery_client = client_for(avery)

    for client in (admin, support):
        response = client.get("/api/nova/stay360/reservations/STAY-HLI-1001")
        assert response.status_code == 404
        assert "Avery Quinn Lane" not in response.text
        assert_clean(response.json())

    own = avery_client.get("/api/nova/stay360/reservations/STAY-HLI-1001")
    other = avery_client.get("/api/nova/stay360/reservations/STAY-HLI-1008")
    foreign = avery_client.get("/api/nova/stay360/reservations/STAY-CRH-2001")
    assert own.status_code == 200
    assert own.json()["guest_label"] == "A. Lane"
    assert other.status_code == 404
    assert foreign.status_code == 404
    assert "Drew Ellis Hale" not in other.text
    assert_clean(own.json(), avery.email)

    assert avery_client.get("/api/nova/stay360/dashboard").status_code == 403
    assert avery_client.get("/api/nova/stay360/reservations").status_code == 403
    assert avery_client.post("/api/nova/stay360/arrivals/refresh", json={}).status_code == 403
    housekeeping = avery_client.post("/api/nova/stay360/rooms/214/housekeeping", json={"status": "inspected"})
    assert housekeeping.status_code == 403
    assert housekeeping.json()["detail"]["code"] == "role_not_permitted"


def test_same_room_number_is_isolated_and_out_of_order_is_admin_only():
    harbor = client_for(user("staff-harbor", "staff", HARBOR_TENANT))
    cedar = client_for(user("staff-cedar", "staff", CEDAR_TENANT))
    updated = harbor.post("/api/nova/stay360/rooms/214/housekeeping", json={"status": "in_progress"})
    assert updated.status_code == 200
    cedar_room = cedar.get("/api/nova/stay360/rooms")
    assert cedar_room.status_code == 200
    room = next(item for item in cedar_room.json() if item["room_number"] == "214")
    assert room["housekeeping_status"] == "inspected"
    assert room["reservation_reference"] == "STAY-CRH-2001"
    assert_clean(cedar_room.json())

    blocked = harbor.post("/api/nova/stay360/rooms/118/housekeeping", json={"status": "out_of_order"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "admin_required"

    admin = client_for(user("admin-harbor", "admin", HARBOR_TENANT))
    changed = admin.post("/api/nova/stay360/rooms/118/housekeeping", json={"status": "out_of_order"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["room"]["room_readiness"] == "blocked"
    drew = client_for(user("guest-drew", "rider", HARBOR_TENANT))
    denied = drew.post("/api/nova/stay360/reservations/STAY-HLI-1008/mobile-check-in", json={})
    assert denied.status_code == 409
    assert denied.json()["detail"]["result"]["check_in_blockers"] == ["room_out_of_order"]
    assert denied.json()["detail"]["result"]["door_access"] == "not_issued"
    assert denied.json()["detail"]["result"]["payment_captured"] is False


def test_denied_roles_unenrolled_orgs_and_anonymous_calls_cannot_read_operations():
    driver = client_for(user("driver-harbor", "driver", HARBOR_TENANT))
    dispatcher = client_for(user("dispatch-harbor", "dispatcher", HARBOR_TENANT))
    stranger = client_for(user("staff-other", "staff", "org-not-a-hotel"))
    blank = client_for(user("staff-blank", "staff", ""))
    rider = client_for(user("rider-other", "rider", "org-not-a-hotel"))

    for client in (driver, dispatcher, stranger, blank, rider):
        response = client.get("/api/nova/stay360/dashboard")
        assert response.status_code == 403
        assert "A. Lane" not in response.text
        assert_clean(response.json())
    assert driver.get("/api/nova/stay360/dashboard").json()["detail"]["code"] == "role_not_permitted"
    assert stranger.get("/api/nova/stay360/dashboard").json()["detail"]["code"] == "tenant_not_enrolled"

    anonymous = anonymous_client()
    assert anonymous.get("/api/nova/stay360/dashboard").status_code == 401
    assert anonymous.get("/api/nova/stay360/reservations/STAY-HLI-1001").status_code == 401
    assert anonymous.post("/api/nova/stay360/arrivals/refresh", json={}).status_code == 401
    assert anonymous.get("/api/nova/stay360/meta").status_code == 200

    staff = client_for(user("staff-harbor", "staff", HARBOR_TENANT))
    payment = staff.post(
        "/api/nova/stay360/reservations/STAY-HLI-1008/mobile-check-in",
        json={"payment_method": "tok_synth_should_not_post"},
    )
    provider = staff.post("/api/nova/stay360/arrivals/refresh", json={"provider": "live-airline"})
    assert payment.status_code == 422
    assert provider.status_code == 422
    listed = staff.get("/api/nova/stay360/reservations/STAY-HLI-1008")
    assert listed.json()["check_in_status"] == "not_checked_in"


def test_identity_query_params_do_not_mutate_refresh_housekeeping_or_check_in():
    staff = client_for(user("staff-harbor", "staff", HARBOR_TENANT))
    secret_email = "guest-casey@example.invalid"
    secret_phone = "+1-555-010-CRH2001"
    secret_name = "Casey Rowan Reed"

    before = staff.get("/api/nova/stay360/reservations/STAY-HLI-1001").json()
    refresh = staff.post(
        "/api/nova/stay360/arrivals/refresh",
        params={"email": secret_email},
        json={},
    )
    assert refresh.status_code == 422
    assert refresh.json()["detail"]["code"] == "sensitive_lookup_rejected"
    assert secret_email not in refresh.text
    after = staff.get("/api/nova/stay360/reservations/STAY-HLI-1001").json()
    assert after["arrival_status"] == before["arrival_status"]
    assert_clean(refresh.json())

    housekeeping = staff.post(
        "/api/nova/stay360/rooms/214/housekeeping",
        params={"phone": secret_phone},
        json={"status": "in_progress"},
    )
    assert housekeeping.status_code == 422
    assert housekeeping.json()["detail"]["code"] == "sensitive_lookup_rejected"
    assert secret_phone not in housekeeping.text
    room = next(item for item in staff.get("/api/nova/stay360/rooms").json() if item["room_number"] == "214")
    assert room["housekeeping_status"] == "dirty"
    assert_clean(housekeeping.json())

    checkin = staff.post(
        "/api/nova/stay360/reservations/STAY-HLI-1008/mobile-check-in",
        params={"legal_name": secret_name},
        json={},
    )
    assert checkin.status_code == 422
    assert checkin.json()["detail"]["code"] == "sensitive_lookup_rejected"
    assert secret_name not in checkin.text
    drew = staff.get("/api/nova/stay360/reservations/STAY-HLI-1008").json()
    assert drew["check_in_status"] == "not_checked_in"
    assert_clean(checkin.json())


def test_parking_is_tenant_scoped_and_does_not_issue_gate_access():
    harbor = client_for(user("staff-harbor", "staff", HARBOR_TENANT))
    cedar = client_for(user("staff-cedar", "staff", CEDAR_TENANT))
    guest = client_for(user("guest-avery", "rider", HARBOR_TENANT))
    other_guest = client_for(user("guest-drew", "rider", HARBOR_TENANT))
    driver = client_for(user("driver-harbor", "driver", HARBOR_TENANT))

    harbor_list = harbor.get("/api/nova/stay360/parking")
    cedar_list = cedar.get("/api/nova/stay360/parking")
    assert harbor_list.status_code == 200, harbor_list.text
    assert cedar_list.status_code == 200, cedar_list.text
    harbor_codes = {row["stall_code"] for row in harbor_list.json()["stalls"]}
    cedar_codes = {row["stall_code"] for row in cedar_list.json()["stalls"]}
    assert "P12" in harbor_codes and "P12" in cedar_codes
    harbor_p12 = next(row for row in harbor_list.json()["stalls"] if row["stall_code"] == "P12")
    cedar_p12 = next(row for row in cedar_list.json()["stalls"] if row["stall_code"] == "P12")
    assert harbor_p12["vehicle_label"] == "Blue sedan"
    assert cedar_p12["vehicle_label"] == "Silver wagon"
    assert harbor_p12["gate_access"] == "not_issued"
    assert harbor_p12["payment_captured"] is False
    assert "C. Reed" not in harbor_list.text
    assert "A. Lane" not in cedar_list.text
    assert_clean(harbor_list.json())
    assert_clean(cedar_list.json())

    own = guest.get("/api/nova/stay360/parking")
    assert own.status_code == 200
    assert [row["stall_code"] for row in own.json()["stalls"]] == ["P12"]
    assert own.json()["stalls"][0]["guest_label"] == "A. Lane"
    drew = other_guest.get("/api/nova/stay360/parking")
    assert [row["stall_code"] for row in drew.json()["stalls"]] == ["P04"]
    assert "A. Lane" not in drew.text
    assert "Blue sedan" not in drew.text

    denied = guest.post("/api/nova/stay360/parking/P12/status", json={"status": "occupied"})
    assert denied.status_code == 403
    assert harbor.get("/api/nova/stay360/parking").json()["stalls"]
    still = next(row for row in harbor.get("/api/nova/stay360/parking").json()["stalls"] if row["stall_code"] == "P12")
    assert still["status"] == "assigned"

    hidden = harbor.post("/api/nova/stay360/parking/P12/status", params={"email": "guest-casey@example.invalid"}, json={"status": "occupied"})
    assert hidden.status_code == 422
    assert hidden.json()["detail"]["code"] == "sensitive_lookup_rejected"
    unchanged = next(row for row in harbor.get("/api/nova/stay360/parking").json()["stalls"] if row["stall_code"] == "P12")
    assert unchanged["status"] == "assigned"
    assert "guest-casey@example.invalid" not in hidden.text

    missing = harbor.post("/api/nova/stay360/parking/P99/status", json={"status": "occupied"})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "stall_not_found"
    assert driver.get("/api/nova/stay360/parking").status_code == 403
    assert anonymous_client().get("/api/nova/stay360/parking").status_code == 401


def test_dashboard_script_uses_the_current_token_and_clears_the_previous_hotel():
    node = shutil.which("node")
    script = Path(__file__).resolve().parent / "stay360_dashboard_behavior.test.cjs"
    completed = subprocess.run(
        [node, "--test", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_lookup_reference_must_match_the_contract_shape():
    staff = client_for(user("staff-harbor", "staff", HARBOR_TENANT))
    response = staff.get("/api/nova/stay360/reservations/not a reference")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_reference"
    assert_clean(response.json())
