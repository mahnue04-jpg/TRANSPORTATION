"""Authorized Lifesaver hardware simulation routes. No vendor device I/O."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.db.session import get_db
from app.modules.lifesaver.hardware import pairing, service
from app.modules.lifesaver.hardware.device_contract import contract_example
from app.modules.lifesaver.hardware.hardware_mode import snapshot as hardware_mode_snapshot
from app.modules.lifesaver.hardware.prototype_config import CAR_HUB_PROTOTYPE, HOME_HUB_PROTOTYPE
from app.modules.lifesaver.hardware.schemas import (
    DiscoverRequest,
    HardwareCommand,
    HardwareSensorEvent,
    PairConfirm,
    SafetyReviewAction,
    SimulatedDeviceCreate,
    VideoSessionCreate,
)
from app.modules.lifesaver.models import ensure_lifesaver_schema
from app.responses import normalize_success

router = APIRouter(prefix="/devices", tags=["lifesaver-devices"])


def _db(db: Session = Depends(get_db)) -> Session:
    ensure_lifesaver_schema()
    return db


@router.get("")
@router.get("/")
def get_devices(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_devices(db, ctx, member_profile_id))


@router.get("/hardware-mode")
def get_hardware_mode(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    ctx
    db
    return normalize_success(data=hardware_mode_snapshot())


@router.get("/contract")
@router.get("/device-contract")
def get_device_contract(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    ctx
    db
    return normalize_success(data=contract_example())


@router.get("/prototype-config")
def get_prototype_config(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    ctx
    db
    return normalize_success(
        data={
            "home_hub": HOME_HUB_PROTOTYPE,
            "car_hub": CAR_HUB_PROTOTYPE,
            "manufacturer_locked": False,
            "real_hardware_bound": False,
        }
    )


@router.get("/pairings")
def get_pairings(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=pairing.list_pairings(db, ctx))


@router.post("/discover")
def post_discover(
    payload: DiscoverRequest,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=pairing.discover(db, ctx, payload))


@router.post("/pairings/{pairing_id}/request")
def post_pair_request(
    pairing_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=pairing.request_pair(db, ctx, pairing_id))


@router.post("/pairings/{pairing_id}/confirm")
def post_pair_confirm(
    pairing_id: str,
    payload: PairConfirm,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=pairing.confirm_pair(db, ctx, pairing_id, payload))


@router.post("/pairings/{pairing_id}/unpair")
def post_unpair(
    pairing_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=pairing.unpair(db, ctx, pairing_id))


@router.post("/simulated")
def post_simulated_device(
    payload: SimulatedDeviceCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_simulated(db, ctx, payload))


@router.get("/{device_id}")
def get_device(
    device_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.get_device(db, ctx, device_id))


@router.get("/{device_id}/health")
def get_device_health(
    device_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.get_health(db, ctx, device_id))


@router.post("/{device_id}/commands")
def post_device_command(
    device_id: str,
    payload: HardwareCommand,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.run_command(db, ctx, device_id, payload))


@router.post("/{device_id}/hardware-events")
def post_hardware_event(
    device_id: str,
    payload: HardwareSensorEvent,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.ingest_hardware_event(db, ctx, device_id, payload.event_type, payload.confidence))


@router.post("/{device_id}/simulate-fall")
def post_simulate_fall(
    device_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.simulate_fall(db, ctx, device_id))


@router.get("/{device_id}/commands")
def get_device_commands(
    device_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_commands(db, ctx, device_id))


@router.get("/{device_id}/events")
def get_device_events(
    device_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_events(db, ctx, device_id))


@router.post("/events/{event_id}/review")
def post_review_safety(
    event_id: str,
    payload: SafetyReviewAction,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.review_safety(db, ctx, event_id, payload.review_status))


@router.post("/events/{event_id}/acknowledge")
def post_acknowledge_safety(
    event_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.acknowledge_safety(db, ctx, event_id))


@router.get("/{device_id}/video-sessions")
def get_video_sessions(
    device_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_video(db, ctx, device_id))


@router.post("/{device_id}/video-sessions")
def post_video_session(
    device_id: str,
    payload: VideoSessionCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.request_video(db, ctx, device_id, payload))


@router.post("/video-sessions/{session_id}/accept")
def post_accept_video(
    session_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.resolve_video(db, ctx, session_id, accept=True))


@router.post("/video-sessions/{session_id}/activate")
def post_activate_video(
    session_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.activate_video(db, ctx, session_id))


@router.post("/video-sessions/{session_id}/end")
def post_end_video(
    session_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.end_video(db, ctx, session_id))


@router.post("/video-sessions/{session_id}/decline")
def post_decline_video(
    session_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.resolve_video(db, ctx, session_id, accept=False))
