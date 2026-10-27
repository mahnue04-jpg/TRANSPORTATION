"""Stay360 operations: privacy-safe lookup, mock arrivals, readiness, simulated check-in."""

from __future__ import annotations

import re

from .access import Stay360Actor
from .constants import (
    ADMIN_ROLES,
    ADMIN_TRANSITIONS,
    DESCRIPTOR,
    FIXTURE_DATE,
    PRODUCT_NAME,
    STAFF_TRANSITIONS,
)
from .errors import Stay360Error
from .privacy import PUBLIC_RESERVATION_KEYS, PUBLIC_ROOM_KEYS, project
from .schemas import (
    ArrivalRefreshResult,
    CheckInDenied,
    DashboardCounts,
    DashboardResponse,
    GuestPrearrivalResponse,
    HousekeepingResult,
    MobileCheckInResult,
    ReservationListResponse,
    ReservationView,
    RoomView,
)
from .store import STORE

REFERENCE_RE = re.compile(r"^STAY-[A-Z0-9]+(?:-[A-Z0-9]+)+$")
ROOM_RE = re.compile(r"^[0-9]{3}$")
NOT_FOUND = "That reservation reference was not found for this hotel."


def _readiness(status: str) -> str:
    if status == "out_of_order":
        return "blocked"
    if status == "inspected":
        return "ready"
    if status == "in_progress":
        return "cleaning"
    return "not_ready"


def _blockers(reservation: dict, room: dict) -> list[str]:
    found: list[str] = []
    if reservation["check_in_status"] == "simulated_checked_in":
        found.append("already_checked_in")
    if reservation["arrival_date"] != FIXTURE_DATE:
        found.append("arrival_date_not_today")
    if not reservation["preverified"]:
        found.append("identity_not_preverified")
    if reservation["balance_due"]:
        found.append("balance_review_required")
    housekeeping = room["housekeeping_status"]
    if housekeeping == "out_of_order":
        found.append("room_out_of_order")
    elif housekeeping != "inspected":
        found.append("room_not_ready")
    return found


def _validate_reference(reference: str) -> str:
    cleaned = str(reference or "").strip().upper()
    if not REFERENCE_RE.match(cleaned):
        raise Stay360Error(
            422,
            "invalid_reference",
            "Reservation lookup accepts a reservation reference only.",
        )
    return cleaned


def _locate(tenants: dict, reference: str):
    for tenant in tenants.values():
        for reservation in tenant["reservations"]:
            if reservation["reference"] == reference:
                guest = tenant["guests"][reservation["guest_user_id"]]
                room = tenant["rooms"][reservation["room_number"]]
                return tenant, reservation, guest, room
    return None


def _reservation_view(reservation: dict, guest: dict, room: dict) -> dict:
    step = reservation["arrival"]["steps"][reservation["arrival"]["index"]]
    blockers = _blockers(reservation, room)
    raw = {
        "reservation_reference": reservation["reference"],
        "guest_label": guest["guest_label"],
        "room_number": reservation["room_number"],
        "arrival_date": reservation["arrival_date"],
        "departure_date": reservation["departure_date"],
        "arrival_mode": reservation["arrival"]["mode"],
        "arrival_status": step["status"],
        "arrival_detail": step["detail"],
        "eta_local": step["eta_local"],
        "housekeeping_status": room["housekeeping_status"],
        "room_readiness": _readiness(room["housekeeping_status"]),
        "check_in_eligibility": "eligible" if not blockers else "ineligible",
        "check_in_blockers": blockers,
        "check_in_status": reservation["check_in_status"],
    }
    return project(raw, PUBLIC_RESERVATION_KEYS)


def _room_view(tenant: dict, room_number: str) -> dict:
    room = tenant["rooms"][room_number]
    reservation = next(
        item for item in tenant["reservations"] if item["room_number"] == room_number
    )
    guest = tenant["guests"][reservation["guest_user_id"]]
    raw = {
        "room_number": room_number,
        "housekeeping_status": room["housekeeping_status"],
        "room_readiness": _readiness(room["housekeeping_status"]),
        "reservation_reference": reservation["reference"],
        "guest_label": guest["guest_label"],
    }
    return project(raw, PUBLIC_ROOM_KEYS)


def _views(tenant: dict) -> list[dict]:
    rows = []
    for reservation in tenant["reservations"]:
        guest = tenant["guests"][reservation["guest_user_id"]]
        room = tenant["rooms"][reservation["room_number"]]
        rows.append(_reservation_view(reservation, guest, room))
    return rows


def _require_hotel(actor: Stay360Actor) -> None:
    if actor.kind != "hotel":
        raise Stay360Error(
            403,
            "role_not_permitted",
            "This Stay360 action is limited to hotel staff.",
        )


class Stay360Service:
    """Tenant-scoped hotel operations over the in-memory fixture store."""

    provider_calls = 0

    def __init__(self, store=STORE) -> None:
        self.store = store

    def dashboard(self, actor: Stay360Actor) -> DashboardResponse:
        _require_hotel(actor)

        def read(tenants: dict) -> DashboardResponse:
            tenant = tenants[actor.tenant_id]
            arrivals = [ReservationView(**row) for row in _views(tenant)]
            rooms = [
                RoomView(**_room_view(tenant, room_number))
                for room_number in sorted(tenant["rooms"])
            ]
            counts = DashboardCounts(
                reservations=len(arrivals),
                arrivals_today=sum(1 for row in arrivals if row.arrival_date == FIXTURE_DATE),
                rooms_ready=sum(1 for room in rooms if room.room_readiness == "ready"),
                rooms_not_ready=sum(1 for room in rooms if room.room_readiness != "ready"),
                eligible_check_in=sum(1 for row in arrivals if row.check_in_eligibility == "eligible"),
                simulated_checked_in=sum(
                    1 for row in arrivals if row.check_in_status == "simulated_checked_in"
                ),
            )
            return DashboardResponse(
                product_name=PRODUCT_NAME,
                descriptor=DESCRIPTOR,
                tenant_id=actor.tenant_id,
                hotel_name=tenant["hotel_name"],
                fixture_date=FIXTURE_DATE,
                synthetic=True,
                counts=counts,
                arrivals=arrivals,
                rooms=rooms,
            )

        return self.store.read(read)

    def list_reservations(
        self,
        actor: Stay360Actor,
        reservation_reference: str | None = None,
    ) -> ReservationListResponse:
        _require_hotel(actor)
        reference = _validate_reference(reservation_reference) if reservation_reference else None

        def read(tenants: dict) -> ReservationListResponse:
            rows = [ReservationView(**row) for row in _views(tenants[actor.tenant_id])]
            if reference is not None:
                rows = [row for row in rows if row.reservation_reference == reference]
            return ReservationListResponse(synthetic=True, reservations=rows)

        return self.store.read(read)

    def lookup(self, actor: Stay360Actor, reference: str) -> ReservationView:
        cleaned = _validate_reference(reference)

        def read(tenants: dict) -> ReservationView:
            located = _locate(tenants, cleaned)
            if located is None:
                raise Stay360Error(404, "reservation_not_found", NOT_FOUND)
            tenant, reservation, guest, room = located
            if tenant["tenant_id"] != actor.tenant_id:
                raise Stay360Error(404, "reservation_not_found", NOT_FOUND)
            if actor.kind == "guest" and reservation["guest_user_id"] != actor.user_id:
                raise Stay360Error(404, "reservation_not_found", NOT_FOUND)
            return ReservationView(**_reservation_view(reservation, guest, room))

        return self.store.read(read)

    def prearrival(self, actor: Stay360Actor) -> GuestPrearrivalResponse:
        if actor.kind != "guest":
            raise Stay360Error(
                403,
                "role_not_permitted",
                "Guest prearrival is limited to the bound guest.",
            )

        def read(tenants: dict) -> GuestPrearrivalResponse:
            tenant = tenants[actor.tenant_id]
            matches = [
                reservation
                for reservation in tenant["reservations"]
                if reservation["guest_user_id"] == actor.user_id
            ]
            if len(matches) != 1:
                raise Stay360Error(
                    404,
                    "guest_reservation_not_found",
                    "No Stay360 reservation is bound to this guest.",
                )
            reservation = matches[0]
            guest = tenant["guests"][reservation["guest_user_id"]]
            room = tenant["rooms"][reservation["room_number"]]
            return GuestPrearrivalResponse(
                product_name=PRODUCT_NAME,
                descriptor=DESCRIPTOR,
                synthetic=True,
                door_access="not_issued",
                physical_access_control=False,
                payment_captured=False,
                reservation=ReservationView(**_reservation_view(reservation, guest, room)),
            )

        return self.store.read(read)

    def refresh_arrivals(self, actor: Stay360Actor) -> ArrivalRefreshResult:
        """Advance scripted flight and road fixtures one step. No network call is made."""
        _require_hotel(actor)

        def write(tenants: dict) -> ArrivalRefreshResult:
            tenant = tenants[actor.tenant_id]
            for reservation in tenant["reservations"]:
                arrival = reservation["arrival"]
                last = len(arrival["steps"]) - 1
                if arrival["index"] < last:
                    arrival["index"] += 1
            rows = [ReservationView(**row) for row in _views(tenant)]
            return ArrivalRefreshResult(
                synthetic=True,
                network_providers="disabled",
                reservations=rows,
            )

        return self.store.write(write)

    def update_housekeeping(
        self,
        actor: Stay360Actor,
        room_number: str,
        status: str,
    ) -> HousekeepingResult:
        _require_hotel(actor)
        cleaned_room = str(room_number or "").strip()
        if not ROOM_RE.match(cleaned_room):
            raise Stay360Error(422, "invalid_room", "Room numbers use three digits.")

        def write(tenants: dict) -> HousekeepingResult:
            tenant = tenants[actor.tenant_id]
            room = tenant["rooms"].get(cleaned_room)
            if room is None:
                raise Stay360Error(404, "room_not_found", "That room was not found for this hotel.")
            current = room["housekeeping_status"]
            transitions = ADMIN_TRANSITIONS if actor.role in ADMIN_ROLES else STAFF_TRANSITIONS
            if status not in transitions[current]:
                if actor.role not in ADMIN_ROLES and (
                    status == "out_of_order" or current == "out_of_order"
                ):
                    raise Stay360Error(
                        403,
                        "admin_required",
                        "Only a hotel admin can change an out-of-order room.",
                    )
                raise Stay360Error(
                    409,
                    "invalid_transition",
                    "That housekeeping transition is not allowed.",
                )
            room["housekeeping_status"] = status
            reservation = next(
                item for item in tenant["reservations"] if item["room_number"] == cleaned_room
            )
            guest = tenant["guests"][reservation["guest_user_id"]]
            return HousekeepingResult(
                room=RoomView(**_room_view(tenant, cleaned_room)),
                reservation=ReservationView(**_reservation_view(reservation, guest, room)),
            )

        return self.store.write(write)

    def simulate_check_in(self, actor: Stay360Actor, reference: str) -> MobileCheckInResult:
        cleaned = _validate_reference(reference)

        def write(tenants: dict) -> MobileCheckInResult:
            located = _locate(tenants, cleaned)
            if located is None:
                raise Stay360Error(404, "reservation_not_found", NOT_FOUND)
            tenant, reservation, _guest, room = located
            if tenant["tenant_id"] != actor.tenant_id:
                raise Stay360Error(404, "reservation_not_found", NOT_FOUND)
            if actor.kind == "guest" and reservation["guest_user_id"] != actor.user_id:
                raise Stay360Error(404, "reservation_not_found", NOT_FOUND)
            blockers = _blockers(reservation, room)
            if blockers:
                denied = CheckInDenied(
                    reservation_reference=cleaned,
                    outcome="not_eligible",
                    check_in_blockers=blockers,
                    door_access="not_issued",
                    physical_access_control=False,
                    payment_captured=False,
                )
                raise Stay360Error(
                    409,
                    "not_eligible",
                    "Mobile check-in is not eligible yet.",
                    denied.model_dump(),
                )
            reservation["check_in_status"] = "simulated_checked_in"
            return MobileCheckInResult(
                reservation_reference=cleaned,
                outcome="simulated",
                check_in_status="simulated_checked_in",
                room_number=reservation["room_number"],
                door_access="not_issued",
                physical_access_control=False,
                payment_captured=False,
                confirmation_code=f"SIM-{cleaned}",
            )

        return self.store.write(write)


def get_service() -> Stay360Service:
    return Stay360Service(STORE)
