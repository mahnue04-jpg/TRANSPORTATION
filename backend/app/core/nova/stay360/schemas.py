"""API contracts for the Stay360 guest-to-room-readiness slice."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

HousekeepingStatus = Literal["dirty", "in_progress", "inspected", "out_of_order"]
ArrivalMode = Literal["flight", "road"]
Eligibility = Literal["eligible", "ineligible"]
CheckInStatus = Literal["not_checked_in", "simulated_checked_in"]
Readiness = Literal["ready", "cleaning", "not_ready", "blocked"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReservationView(_Strict):
    reservation_reference: str
    guest_label: str
    room_number: str
    arrival_date: str
    departure_date: str
    arrival_mode: ArrivalMode
    arrival_status: str
    arrival_detail: str
    eta_local: str
    housekeeping_status: HousekeepingStatus
    room_readiness: Readiness
    check_in_eligibility: Eligibility
    check_in_blockers: list[str]
    check_in_status: CheckInStatus


class RoomView(_Strict):
    room_number: str
    housekeeping_status: HousekeepingStatus
    room_readiness: Readiness
    reservation_reference: str
    guest_label: str


class DashboardCounts(_Strict):
    reservations: int
    arrivals_today: int
    rooms_ready: int
    rooms_not_ready: int
    eligible_check_in: int
    simulated_checked_in: int


class DashboardResponse(_Strict):
    product_name: str
    descriptor: str
    tenant_id: str
    hotel_name: str
    fixture_date: str
    synthetic: Literal[True]
    counts: DashboardCounts
    arrivals: list[ReservationView]
    rooms: list[RoomView]


class ReservationListResponse(_Strict):
    synthetic: Literal[True]
    reservations: list[ReservationView]


class ArrivalRefreshResult(_Strict):
    synthetic: Literal[True]
    network_providers: Literal["disabled"]
    reservations: list[ReservationView]


class HousekeepingUpdate(_Strict):
    status: HousekeepingStatus


class HousekeepingResult(_Strict):
    room: RoomView
    reservation: ReservationView


class MobileCheckInRequest(_Strict):
    """Empty on purpose. Payment and door fields are rejected."""


class MobileCheckInResult(_Strict):
    reservation_reference: str
    outcome: Literal["simulated"]
    check_in_status: Literal["simulated_checked_in"]
    room_number: str
    door_access: Literal["not_issued"]
    physical_access_control: Literal[False]
    payment_captured: Literal[False]
    confirmation_code: str


class CheckInDenied(_Strict):
    reservation_reference: str
    outcome: Literal["not_eligible"]
    check_in_blockers: list[str]
    door_access: Literal["not_issued"]
    physical_access_control: Literal[False]
    payment_captured: Literal[False]


class GuestPrearrivalResponse(_Strict):
    product_name: str
    descriptor: str
    synthetic: Literal[True]
    door_access: Literal["not_issued"]
    physical_access_control: Literal[False]
    payment_captured: Literal[False]
    reservation: ReservationView


class MetaResponse(_Strict):
    product_name: str
    descriptor: str
    slice_id: str
    synthetic_only: Literal[True]
    fixture_clock_date: str
    fixture_clock_timezone: str
    network_providers: Literal["disabled"]
    payment_capture: Literal[False]
    physical_access_control: Literal[False]
    door_access: Literal["not_issued"]
    supported_locales: list[str]
    not_implemented: list[str]
    blueprint_note: str


class LocaleIndex(_Strict):
    locales: list[str]
    keys: list[str]


class LocaleCatalog(_Strict):
    code: str
    strings: dict[str, str]


class ArrivalRefreshRequest(_Strict):
    """Empty on purpose. A provider name is not accepted."""
