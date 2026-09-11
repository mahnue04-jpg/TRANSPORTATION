"""HTTP API for simulated connected-health and home-test coordination."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.db.session import get_db
from app.modules.lifesaver.connected_health import ecosystem, service
from app.modules.lifesaver.connected_health.schemas import (
    ConnectedDeviceCreate,
    ConnectedReadingCreate,
    HomeTestKitCreate,
    KitTransition,
    ResultDocumentCreate,
)
from app.modules.lifesaver.models import ensure_lifesaver_schema
from app.responses import normalize_success

router = APIRouter(prefix="/connected-health", tags=["lifesaver-connected-health"])


def _db(db: Session = Depends(get_db)) -> Session:
    ensure_lifesaver_schema()
    return db


@router.get("/meta")
def get_meta():
    return normalize_success(data=service.meta())


@router.get("/ecosystem")
def get_ecosystem():
    return normalize_success(data=ecosystem.snapshot())


@router.get("/devices")
def get_devices(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_devices(db, ctx, member_profile_id))


@router.post("/devices")
def post_device(
    payload: ConnectedDeviceCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_device(db, ctx, payload))


@router.post("/devices/{device_id}/pair")
def post_pair(
    device_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.pair_device(db, ctx, device_id, member_profile_id))


@router.post("/devices/{device_id}/offline")
def post_offline(
    device_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.mark_device_offline(db, ctx, device_id, member_profile_id))


@router.post("/devices/{device_id}/revoke")
def post_revoke(
    device_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.revoke_device(db, ctx, device_id, member_profile_id))


@router.get("/devices/{device_id}/readings")
def get_readings(
    device_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_readings(db, ctx, device_id, member_profile_id))


@router.post("/devices/{device_id}/readings")
def post_reading(
    device_id: str,
    payload: ConnectedReadingCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.add_reading(db, ctx, device_id, payload))


@router.get("/kits")
def get_kits(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_kits(db, ctx, member_profile_id))


@router.post("/kits")
def post_kit(
    payload: HomeTestKitCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_kit(db, ctx, payload))


@router.post("/kits/{kit_id}/transition")
def post_kit_transition(
    kit_id: str,
    payload: KitTransition,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.transition_kit(db, ctx, kit_id, payload))


@router.post("/kits/{kit_id}/expire")
def post_kit_expire(
    kit_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.expire_kit(db, ctx, kit_id, member_profile_id))


@router.post("/kits/{kit_id}/provider-share")
def post_kit_provider(
    kit_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.share_kit_provider(db, ctx, kit_id, member_profile_id))


@router.post("/kits/{kit_id}/circle-share")
def post_kit_circle(
    kit_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.share_kit_circle(db, ctx, kit_id, member_profile_id))


@router.get("/results")
def get_results(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_results(db, ctx, member_profile_id))


@router.post("/results")
def post_result(
    payload: ResultDocumentCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_result(db, ctx, payload))


@router.post("/results/{result_id}/acknowledge")
def post_result_ack(
    result_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.acknowledge_result(db, ctx, result_id, member_profile_id))


@router.post("/results/{result_id}/provider-share")
def post_result_provider(
    result_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.share_result_provider(db, ctx, result_id, member_profile_id))


@router.post("/results/{result_id}/circle-share")
def post_result_circle(
    result_id: str,
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.share_result_circle(db, ctx, result_id, member_profile_id))


@router.get("/hub-summary")
def get_hub_summary(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.hub_summary(db, ctx, member_profile_id))
