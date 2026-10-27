"""Stay360 guest-to-room readiness flow on synthetic fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from stay360_support import HARBOR_TENANT, assert_clean, client_for, reset_stay360_store, user


@pytest.fixture(autouse=True)
def _reset():
    reset_stay360_store()
    yield
    reset_stay360_store()


def _row(payload, reference):
    rows = payload["reservations"] if "reservations" in payload else payload["arrivals"]
    return next(row for row in rows if row["reservation_reference"] == reference)


def test_mock_arrivals_housekeeping_and_mobile_check_in():
    staff = user("staff-harbor", "staff", HARBOR_TENANT)
    guest = user("guest-avery", "rider", HARBOR_TENANT)
    staff_client = client_for(staff)
    guest_client = client_for(guest)

    dashboard = staff_client.get("/api/nova/stay360/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    board = dashboard.json()
    assert board["product_name"] == "AMICOR Nova Stay360"
    assert board["descriptor"] == "Intelligent Hospitality Operations"
    assert board["hotel_name"] == "Harbor Lantern Inn"
    assert board["fixture_date"] == "2026-10-26"
    assert board["counts"] == {
        "reservations": 6,
        "arrivals_today": 5,
        "rooms_ready": 4,
        "rooms_not_ready": 2,
        "eligible_check_in": 1,
        "simulated_checked_in": 0,
    }
    avery = _row(board, "STAY-HLI-1001")
    drew = _row(board, "STAY-HLI-1008")
    blair = _row(board, "STAY-HLI-1002")
    assert avery["guest_label"] == "A. Lane"
    assert avery["arrival_mode"] == "flight"
    assert avery["arrival_status"] == "scheduled"
    assert avery["check_in_blockers"] == ["room_not_ready"]
    assert drew["arrival_status"] == "landed"
    assert drew["check_in_eligibility"] == "eligible"
    assert blair["arrival_mode"] == "road"
    assert blair["arrival_status"] == "en_route"
    assert_clean(board, staff.email)

    prearrival = guest_client.get("/api/nova/stay360/prearrival")
    assert prearrival.status_code == 200, prearrival.text
    assert prearrival.json()["reservation"]["reservation_reference"] == "STAY-HLI-1001"
    assert prearrival.json()["payment_captured"] is False
    assert prearrival.json()["door_access"] == "not_issued"
    assert_clean(prearrival.json(), guest.email)

    denied = guest_client.post("/api/nova/stay360/reservations/STAY-HLI-1001/mobile-check-in", json={})
    assert denied.status_code == 409, denied.text
    denial = denied.json()["detail"]["result"]
    assert denial["check_in_blockers"] == ["room_not_ready"]
    assert denial["door_access"] == "not_issued"
    assert denial["physical_access_control"] is False
    assert denial["payment_captured"] is False
    assert "confirmation_code" not in denial
    assert_clean(denied.json(), guest.email)

    skipped = staff_client.post(
        "/api/nova/stay360/rooms/214/housekeeping",
        json={"status": "inspected"},
    )
    assert skipped.status_code == 409
    assert skipped.json()["detail"]["code"] == "invalid_transition"

    cleaning = staff_client.post(
        "/api/nova/stay360/rooms/214/housekeeping",
        json={"status": "in_progress"},
    )
    assert cleaning.status_code == 200, cleaning.text
    assert cleaning.json()["room"]["room_readiness"] == "cleaning"
    ready = staff_client.post(
        "/api/nova/stay360/rooms/214/housekeeping",
        json={"status": "inspected"},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["room"]["room_readiness"] == "ready"
    assert ready.json()["reservation"]["check_in_eligibility"] == "eligible"
    assert_clean(ready.json(), staff.email)

    refreshed = staff_client.post("/api/nova/stay360/arrivals/refresh", json={})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["network_providers"] == "disabled"
    assert _row(refreshed.json(), "STAY-HLI-1001")["arrival_status"] == "delayed"
    assert _row(refreshed.json(), "STAY-HLI-1001")["eta_local"] == "16:50"
    assert "synthetic hold" in _row(refreshed.json(), "STAY-HLI-1001")["arrival_detail"]
    assert _row(refreshed.json(), "STAY-HLI-1002")["arrival_status"] == "delayed"
    assert "synthetic traffic" in _row(refreshed.json(), "STAY-HLI-1002")["arrival_detail"]
    assert _row(refreshed.json(), "STAY-HLI-1008")["arrival_status"] == "landed"
    assert_clean(refreshed.json(), staff.email)

    landed = staff_client.post("/api/nova/stay360/arrivals/refresh", json={})
    assert _row(landed.json(), "STAY-HLI-1001")["arrival_status"] == "landed"
    held = staff_client.post("/api/nova/stay360/arrivals/refresh", json={})
    assert _row(held.json(), "STAY-HLI-1001")["arrival_status"] == "landed"
    assert _row(held.json(), "STAY-HLI-1002")["arrival_status"] == "arrived"

    checked_in = guest_client.post("/api/nova/stay360/reservations/STAY-HLI-1001/mobile-check-in", json={})
    assert checked_in.status_code == 200, checked_in.text
    result = checked_in.json()
    assert result["outcome"] == "simulated"
    assert result["check_in_status"] == "simulated_checked_in"
    assert result["confirmation_code"] == "SIM-STAY-HLI-1001"
    assert result["door_access"] == "not_issued"
    assert result["physical_access_control"] is False
    assert result["payment_captured"] is False
    assert_clean(result, guest.email)

    again = guest_client.post("/api/nova/stay360/reservations/STAY-HLI-1001/mobile-check-in", json={})
    assert again.status_code == 409
    assert again.json()["detail"]["result"]["check_in_blockers"] == ["already_checked_in"]
    assert again.json()["detail"]["result"]["payment_captured"] is False
    assert again.json()["detail"]["result"]["door_access"] == "not_issued"

    after = staff_client.get("/api/nova/stay360/dashboard")
    assert after.json()["counts"]["simulated_checked_in"] == 1
    assert _row(after.json(), "STAY-HLI-1001")["check_in_status"] == "simulated_checked_in"
    assert_clean(after.json(), staff.email)


def test_other_eligibility_blockers_stay_on_the_simulation():
    guest_finn = client_for(user("guest-finn", "rider", HARBOR_TENANT))
    guest_gray = client_for(user("guest-gray", "rider", HARBOR_TENANT))
    guest_eden = client_for(user("guest-eden", "rider", HARBOR_TENANT))
    finn = guest_finn.post("/api/nova/stay360/reservations/STAY-HLI-1019/mobile-check-in", json={})
    gray = guest_gray.post("/api/nova/stay360/reservations/STAY-HLI-1022/mobile-check-in", json={})
    eden = guest_eden.post("/api/nova/stay360/reservations/STAY-HLI-1015/mobile-check-in", json={})
    assert finn.status_code == 409
    assert finn.json()["detail"]["result"]["check_in_blockers"] == ["balance_review_required"]
    assert finn.json()["detail"]["result"]["payment_captured"] is False
    assert gray.json()["detail"]["result"]["check_in_blockers"] == ["identity_not_preverified"]
    assert eden.json()["detail"]["result"]["check_in_blockers"] == ["arrival_date_not_today"]
    assert_clean(finn.json())
    assert_clean(gray.json())
    assert_clean(eden.json())


def test_staff_can_move_a_stall_only_along_the_synthetic_path():
    staff = client_for(user("staff-harbor", "staff", HARBOR_TENANT))
    skipped = staff.post("/api/nova/stay360/parking/P12/status", json={"status": "released"})
    assert skipped.status_code == 409
    assert skipped.json()["detail"]["code"] == "invalid_parking_transition"
    occupied = staff.post("/api/nova/stay360/parking/P12/status", json={"status": "occupied"})
    assert occupied.status_code == 200, occupied.text
    assert occupied.json()["status"] == "occupied"
    assert occupied.json()["gate_access"] == "not_issued"
    assert occupied.json()["payment_captured"] is False
    released = staff.post("/api/nova/stay360/parking/P12/status", json={"status": "released"})
    assert released.status_code == 200
    assert released.json()["status"] == "released"
    paid = staff.post(
        "/api/nova/stay360/parking/P12/status",
        json={"status": "assigned", "payment_captured": True, "gate_code": "2468"},
    )
    assert paid.status_code == 422
    assert "2468" not in paid.text
    current = next(row for row in staff.get("/api/nova/stay360/parking").json()["stalls"] if row["stall_code"] == "P12")
    assert current["status"] == "released"
    assert_clean(occupied.json())
    assert_clean(released.json())


def test_drew_can_simulate_check_in_when_the_room_is_already_ready():
    guest = user("guest-drew", "rider", HARBOR_TENANT)
    response = client_for(guest).post("/api/nova/stay360/reservations/STAY-HLI-1008/mobile-check-in", json={})
    assert response.status_code == 200, response.text
    assert response.json()["confirmation_code"] == "SIM-STAY-HLI-1008"
    assert response.json()["payment_captured"] is False
    assert response.json()["physical_access_control"] is False
    assert_clean(response.json(), guest.email)
