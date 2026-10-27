"""Invented Stay360 hotels, guests, and arrival scripts. In-process only."""

from __future__ import annotations

from .constants import FIXTURE_DATE, SENSITIVE_FIELDS

HARBOR_TENANT = "org-harbor-lantern"
CEDAR_TENANT = "org-cedar-ridge"


def _arrival(mode: str, service_number: str, steps: list[dict[str, str]], index: int = 0) -> dict:
    carrier = "Fixture Air" if mode == "flight" else "Fixture Road"
    return {
        "mode": mode,
        "carrier_label": carrier,
        "service_number": service_number,
        "steps": steps,
        "index": index,
    }


def _flight(service_number: str, index: int = 0) -> dict:
    return _arrival(
        "flight",
        service_number,
        [
            {"status": "scheduled", "eta_local": "16:10", "detail": f"Fixture Air {service_number} is scheduled"},
            {"status": "delayed", "eta_local": "16:50", "detail": f"Fixture Air {service_number} is in a synthetic hold"},
            {"status": "landed", "eta_local": "16:52", "detail": f"Fixture Air {service_number} has landed"},
        ],
        index,
    )


def _road(service_number: str, index: int = 0) -> dict:
    return _arrival(
        "road",
        service_number,
        [
            {"status": "en_route", "eta_local": "17:05", "detail": f"Fixture road corridor {service_number} is en route"},
            {
                "status": "delayed",
                "eta_local": "17:40",
                "detail": f"Fixture road corridor {service_number} is delayed by synthetic traffic",
            },
            {"status": "arrived", "eta_local": "17:41", "detail": f"Fixture road corridor {service_number} has arrived"},
        ],
        index,
    )


def _guest(
    guest_user_id: str,
    guest_label: str,
    legal_name: str,
    serial: str,
    date_of_birth: str,
) -> dict[str, str]:
    return {
        "guest_user_id": guest_user_id,
        "guest_label": guest_label,
        "legal_name": legal_name,
        "date_of_birth": date_of_birth,
        "email": f"{guest_user_id}@example.invalid",
        "phone": f"+1-555-010-{serial}",
        "government_id": f"SYN-ID-{serial}",
        "passport_number": f"P-SYNTH-{serial}",
        "home_address": f"{serial} Example Lantern Street, Fictional City",
        "payment_instrument_token": f"tok_synth_stay_{serial.lower()}",
        "loyalty_number": f"LY-SYN-{serial}",
    }


def _reservation(
    reference: str,
    guest_user_id: str,
    room_number: str,
    arrival_date: str,
    departure_date: str,
    arrival: dict,
    *,
    preverified: bool,
    balance_due: bool,
) -> dict:
    return {
        "reference": reference,
        "guest_user_id": guest_user_id,
        "room_number": room_number,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "preverified": preverified,
        "balance_due": balance_due,
        "check_in_status": "not_checked_in",
        "arrival": arrival,
    }


def _room(status: str) -> dict[str, str]:
    return {"housekeeping_status": status}


def _tenant(tenant_id: str, hotel_name: str, guests: list[dict], reservations: list[dict], rooms: dict) -> dict:
    return {
        "tenant_id": tenant_id,
        "hotel_name": hotel_name,
        "guests": {guest["guest_user_id"]: guest for guest in guests},
        "reservations": reservations,
        "rooms": rooms,
    }


def build_state() -> dict[str, dict]:
    """Return a fresh synthetic hotel state. Callers must not reuse a mutated copy."""
    harbor_guests = [
        _guest("guest-avery", "A. Lane", "Avery Quinn Lane", "HLI1001", "1990-04-12"),
        _guest("guest-drew", "D. Hale", "Drew Ellis Hale", "HLI1008", "1987-11-03"),
        _guest("guest-blair", "B. Moss", "Blair Nia Moss", "HLI1002", "1994-06-21"),
        _guest("guest-eden", "E. Cho", "Eden Park Cho", "HLI1015", "1992-01-30"),
        _guest("guest-finn", "F. Pell", "Finn Jules Pell", "HLI1019", "1985-09-14"),
        _guest("guest-gray", "G. Holt", "Gray Sol Holt", "HLI1022", "1996-12-08"),
    ]
    harbor_reservations = [
        _reservation(
            "STAY-HLI-1001",
            "guest-avery",
            "214",
            FIXTURE_DATE,
            "2026-10-28",
            _flight("LN441"),
            preverified=True,
            balance_due=False,
        ),
        _reservation(
            "STAY-HLI-1008",
            "guest-drew",
            "118",
            FIXTURE_DATE,
            "2026-10-27",
            _flight("LN508", index=2),
            preverified=True,
            balance_due=False,
        ),
        _reservation(
            "STAY-HLI-1002",
            "guest-blair",
            "305",
            FIXTURE_DATE,
            "2026-10-29",
            _road("RD88"),
            preverified=True,
            balance_due=False,
        ),
        _reservation(
            "STAY-HLI-1015",
            "guest-eden",
            "220",
            "2026-11-02",
            "2026-11-04",
            _flight("LN220"),
            preverified=True,
            balance_due=False,
        ),
        _reservation(
            "STAY-HLI-1019",
            "guest-finn",
            "221",
            FIXTURE_DATE,
            "2026-10-30",
            _road("RD19"),
            preverified=True,
            balance_due=True,
        ),
        _reservation(
            "STAY-HLI-1022",
            "guest-gray",
            "230",
            FIXTURE_DATE,
            "2026-10-28",
            _flight("LN230"),
            preverified=False,
            balance_due=False,
        ),
    ]
    cedar_guests = [
        _guest("guest-casey", "C. Reed", "Casey Rowan Reed", "CRH2001", "1988-02-17"),
    ]
    cedar_reservations = [
        _reservation(
            "STAY-CRH-2001",
            "guest-casey",
            "214",
            FIXTURE_DATE,
            "2026-10-29",
            _road("RD214"),
            preverified=True,
            balance_due=False,
        )
    ]
    state = {
        HARBOR_TENANT: _tenant(
            HARBOR_TENANT,
            "Harbor Lantern Inn",
            harbor_guests,
            harbor_reservations,
            {
                "214": _room("dirty"),
                "118": _room("inspected"),
                "305": _room("in_progress"),
                "220": _room("inspected"),
                "221": _room("inspected"),
                "230": _room("inspected"),
            },
        ),
        CEDAR_TENANT: _tenant(
            CEDAR_TENANT,
            "Cedar Ridge House",
            cedar_guests,
            cedar_reservations,
            {"214": _room("inspected")},
        ),
    }
    assert_synthetic_fixtures(state)
    return state


def assert_synthetic_fixtures(state: dict | None = None) -> None:
    """Fail closed if a fixture stops looking invented."""
    snapshot = state if state is not None else build_state()
    seen_secrets: set[str] = set()
    for tenant in snapshot.values():
        guest_ids = set()
        for guest in tenant["guests"].values():
            if guest["guest_user_id"] in guest_ids:
                raise RuntimeError("duplicate synthetic guest")
            guest_ids.add(guest["guest_user_id"])
            if guest["legal_name"] in guest["guest_label"] or "@" in guest["guest_label"]:
                raise RuntimeError("guest label is not privacy-safe")
            email = guest["email"]
            if not email.endswith("@example.invalid"):
                raise RuntimeError("Stay360 fixtures must use example.invalid email")
            if not guest["phone"].startswith("+1-555-010-"):
                raise RuntimeError("Stay360 fixtures must use the synthetic phone range")
            if not guest["passport_number"].startswith("P-SYNTH-"):
                raise RuntimeError("Stay360 fixtures must use synthetic passport numbers")
            if not guest["government_id"].startswith("SYN-ID-"):
                raise RuntimeError("Stay360 fixtures must use synthetic government ids")
            if not guest["payment_instrument_token"].startswith("tok_synth_stay_"):
                raise RuntimeError("Stay360 fixtures must use synthetic payment tokens")
            if not guest["loyalty_number"].startswith("LY-SYN-"):
                raise RuntimeError("Stay360 fixtures must use synthetic loyalty numbers")
            if "Example" not in guest["home_address"] or "Fictional City" not in guest["home_address"]:
                raise RuntimeError("Stay360 fixtures must use fictional addresses")
            for field in SENSITIVE_FIELDS:
                value = str(guest[field])
                if len(value) < 8 or value in seen_secrets:
                    raise RuntimeError(f"synthetic secret {field} is missing or repeated")
                seen_secrets.add(value)
        for reservation in tenant["reservations"]:
            if reservation["guest_user_id"] not in tenant["guests"]:
                raise RuntimeError("reservation guest is not in the tenant")
            if reservation["room_number"] not in tenant["rooms"]:
                raise RuntimeError("reservation room is not in the tenant")
            if reservation["arrival"]["carrier_label"] not in {"Fixture Air", "Fixture Road"}:
                raise RuntimeError("arrival carrier must stay on the in-process fixture")


def sensitive_corpus() -> tuple[str, ...]:
    values: list[str] = []
    for tenant in build_state().values():
        for guest in tenant["guests"].values():
            for field in SENSITIVE_FIELDS:
                values.append(str(guest[field]))
    return tuple(values)


def public_guest_labels() -> tuple[str, ...]:
    labels: list[str] = []
    for tenant in build_state().values():
        for guest in tenant["guests"].values():
            labels.append(guest["guest_label"])
    return tuple(labels)
