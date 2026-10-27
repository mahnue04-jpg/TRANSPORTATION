"""Stay360 HTTP contracts. Page and API routes are additive."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from app.auth import UserContext, get_current_user_context

from .access import Stay360Actor, actor_from_user
from .constants import (
    ALLOWED_LIST_QUERY,
    BLUEPRINT_NOTE,
    DESCRIPTOR,
    FIXTURE_DATE,
    FIXTURE_TIMEZONE,
    NOT_IMPLEMENTED,
    PRODUCT_NAME,
    SLICE_ID,
    SUPPORTED_LOCALES,
)
from .errors import Stay360Error
from .locales import catalog, locale_keys
from .privacy import assert_safe
from .schemas import (
    ArrivalRefreshRequest,
    ArrivalRefreshResult,
    DashboardResponse,
    GuestPrearrivalResponse,
    HousekeepingResult,
    HousekeepingUpdate,
    LocaleCatalog,
    LocaleIndex,
    MetaResponse,
    MobileCheckInRequest,
    MobileCheckInResult,
    ReservationListResponse,
    ReservationView,
    RoomView,
)
from .service import get_service

_PAGE = Path(__file__).resolve().parents[4] / "static" / "nova-stay360" / "index.html"

router = APIRouter(tags=["nova-stay360"])
api = APIRouter(prefix="/api/nova/stay360", tags=["nova-stay360"])


def _mark(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Stay360-Synthetic"] = "true"


def _guard_query(request: Request, allowed: frozenset[str]) -> None:
    unexpected = set(request.query_params.keys()) - set(allowed)
    if unexpected:
        raise Stay360Error(
            422,
            "sensitive_lookup_rejected",
            "Reservation lookup accepts a reservation reference only.",
        )


def _plain(payload):
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, list):
        return [_plain(item) for item in payload]
    return payload


def _call(action, response: Response, extra: tuple[str, ...] = ()):
    try:
        payload = action()
    except Stay360Error as exc:
        detail = exc.detail()
        try:
            assert_safe(detail, extra)
        except Stay360Error as guard:
            raise HTTPException(status_code=guard.status, detail=guard.detail()) from exc
        raise HTTPException(status_code=exc.status, detail=detail) from exc
    try:
        assert_safe(_plain(payload), extra)
    except Stay360Error as guard:
        raise HTTPException(status_code=guard.status, detail=guard.detail()) from guard
    _mark(response)
    return payload


def require_actor(user: UserContext = Depends(get_current_user_context)) -> Stay360Actor:
    try:
        return actor_from_user(user)
    except Stay360Error as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail()) from exc


@router.get("/nova/stay360", include_in_schema=False)
def stay360_dashboard_page() -> FileResponse:
    if not _PAGE.is_file():
        raise HTTPException(status_code=404, detail={"code": "page_not_found", "message": "Stay360 dashboard page not found"})
    return FileResponse(
        _PAGE,
        media_type="text/html",
        headers={"Cache-Control": "no-store", "X-Stay360-Synthetic": "true"},
    )


@api.get("/meta", response_model=MetaResponse)
def stay360_meta(response: Response) -> MetaResponse:
    payload = MetaResponse(
        product_name=PRODUCT_NAME,
        descriptor=DESCRIPTOR,
        slice_id=SLICE_ID,
        synthetic_only=True,
        fixture_clock_date=FIXTURE_DATE,
        fixture_clock_timezone=FIXTURE_TIMEZONE,
        network_providers="disabled",
        payment_capture=False,
        physical_access_control=False,
        door_access="not_issued",
        supported_locales=list(SUPPORTED_LOCALES),
        not_implemented=list(NOT_IMPLEMENTED),
        blueprint_note=BLUEPRINT_NOTE,
    )
    return _call(lambda: payload, response)


@api.get("/locales", response_model=LocaleIndex)
def stay360_locales(response: Response) -> LocaleIndex:
    payload = LocaleIndex(locales=list(SUPPORTED_LOCALES), keys=sorted(locale_keys()))
    return _call(lambda: payload, response)


@api.get("/locales/{code}", response_model=LocaleCatalog)
def stay360_locale(code: str, response: Response) -> LocaleCatalog:
    def load() -> LocaleCatalog:
        return LocaleCatalog(code=str(code or "").strip().lower(), strings=catalog(code))

    return _call(load, response)


@api.get("/dashboard", response_model=DashboardResponse)
def stay360_dashboard(
    request: Request,
    response: Response,
    actor: Stay360Actor = Depends(require_actor),
) -> DashboardResponse:
    def load() -> DashboardResponse:
        _guard_query(request, frozenset())
        return get_service().dashboard(actor)

    return _call(load, response, (actor.email,))


@api.get("/reservations", response_model=ReservationListResponse)
def stay360_reservations(
    request: Request,
    response: Response,
    reservation_reference: str | None = None,
    actor: Stay360Actor = Depends(require_actor),
) -> ReservationListResponse:
    def load() -> ReservationListResponse:
        _guard_query(request, ALLOWED_LIST_QUERY)
        return get_service().list_reservations(actor, reservation_reference)

    return _call(load, response, (actor.email,))


@api.get("/reservations/{reference}", response_model=ReservationView)
def stay360_lookup(
    reference: str,
    request: Request,
    response: Response,
    actor: Stay360Actor = Depends(require_actor),
) -> ReservationView:
    def load() -> ReservationView:
        _guard_query(request, frozenset())
        return get_service().lookup(actor, reference)

    return _call(load, response, (actor.email,))


@api.get("/prearrival", response_model=GuestPrearrivalResponse)
def stay360_prearrival(
    request: Request,
    response: Response,
    actor: Stay360Actor = Depends(require_actor),
) -> GuestPrearrivalResponse:
    def load() -> GuestPrearrivalResponse:
        _guard_query(request, frozenset())
        return get_service().prearrival(actor)

    return _call(load, response, (actor.email,))


@api.post("/arrivals/refresh", response_model=ArrivalRefreshResult)
def stay360_refresh_arrivals(
    request: Request,
    response: Response,
    _payload: ArrivalRefreshRequest | None = None,
    actor: Stay360Actor = Depends(require_actor),
) -> ArrivalRefreshResult:
    def run() -> ArrivalRefreshResult:
        _guard_query(request, frozenset())
        return get_service().refresh_arrivals(actor)

    return _call(run, response, (actor.email,))


@api.get("/rooms", response_model=list[RoomView])
def stay360_rooms(
    request: Request,
    response: Response,
    actor: Stay360Actor = Depends(require_actor),
) -> list[RoomView]:
    def load() -> list[RoomView]:
        _guard_query(request, frozenset())
        dashboard = get_service().dashboard(actor)
        return dashboard.rooms

    return _call(load, response, (actor.email,))


@api.post("/rooms/{room_number}/housekeeping", response_model=HousekeepingResult)
def stay360_housekeeping(
    room_number: str,
    payload: HousekeepingUpdate,
    request: Request,
    response: Response,
    actor: Stay360Actor = Depends(require_actor),
) -> HousekeepingResult:
    def run() -> HousekeepingResult:
        _guard_query(request, frozenset())
        return get_service().update_housekeeping(actor, room_number, payload.status)

    return _call(run, response, (actor.email,))


@api.post("/reservations/{reference}/mobile-check-in", response_model=MobileCheckInResult)
def stay360_mobile_check_in(
    reference: str,
    request: Request,
    response: Response,
    _payload: MobileCheckInRequest | None = None,
    actor: Stay360Actor = Depends(require_actor),
) -> MobileCheckInResult:
    def run() -> MobileCheckInResult:
        _guard_query(request, frozenset())
        return get_service().simulate_check_in(actor, reference)

    return _call(run, response, (actor.email,))


router.include_router(api)
