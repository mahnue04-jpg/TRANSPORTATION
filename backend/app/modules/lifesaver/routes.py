"""Isolated Lifesaver AI Care Cloud HTTP API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.db.session import get_db
from app.modules.lifesaver import service
from app.modules.lifesaver.models import ensure_lifesaver_schema
from app.modules.lifesaver.schemas import (
    AccessibilityUpdate,
    AiConverse,
    AppointmentCreate,
    CircleInvite,
    CirclePermissionsUpdate,
    ConsentUpdate,
    HandoffCreate,
    JournalCreate,
    MedicationCreate,
    NotificationQueue,
    ProfileUpdate,
    ReadingCreate,
    SimulatedDeviceCreate,
    SosConfirm,
    SosStart,
    TaskCreate,
    TransportConfirm,
    TransportRequestCreate,
    TransportUpdate,
    WellnessCreate,
)
from app.responses import normalize_success

router = APIRouter(prefix="/api/lifesaver", tags=["lifesaver"])


def _db(db: Session = Depends(get_db)) -> Session:
    ensure_lifesaver_schema()
    return db


@router.get("/health")
def lifesaver_health():
    """Public product identity. No user data."""
    return normalize_success(data=service.product_meta())


@router.get("/me")
def get_me(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.bootstrap(db, ctx))


@router.patch("/me")
def patch_me(
    payload: ProfileUpdate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.update_profile(db, ctx, payload))


@router.get("/today")
def get_today(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.today_view(db, ctx, member_profile_id))


@router.get("/consents")
def get_consents(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_consents(db, ctx))


@router.post("/consents")
def post_consent(
    payload: ConsentUpdate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.set_consent(db, ctx, payload.consent_type, payload.granted))


@router.put("/accessibility")
def put_accessibility(
    payload: AccessibilityUpdate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.update_accessibility(db, ctx, payload))


@router.get("/medications")
def get_medications(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_medications(db, ctx, member_profile_id))


@router.post("/medications")
def post_medication(
    payload: MedicationCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_medication(db, ctx, payload))


@router.delete("/medications/{medication_id}")
def delete_medication(
    medication_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.deactivate_medication(db, ctx, medication_id))


@router.get("/reminders")
def get_reminders(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_reminders(db, ctx, member_profile_id))


@router.post("/reminders/{reminder_id}/acknowledge")
def post_acknowledge_reminder(
    reminder_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.acknowledge_reminder(db, ctx, reminder_id))


@router.get("/appointments")
def get_appointments(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_appointments(db, ctx, member_profile_id))


@router.post("/appointments")
def post_appointment(
    payload: AppointmentCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_appointment(db, ctx, payload))


@router.get("/wellness")
def get_wellness(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_wellness(db, ctx, member_profile_id))


@router.post("/wellness")
def post_wellness(
    payload: WellnessCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_wellness(db, ctx, payload))


@router.get("/journal")
def get_journal(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_journal(db, ctx, member_profile_id))


@router.post("/journal")
def post_journal(
    payload: JournalCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_journal(db, ctx, payload))


@router.get("/readings")
def get_readings(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_readings(db, ctx, member_profile_id))


@router.post("/readings")
def post_reading(
    payload: ReadingCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_reading(db, ctx, payload))


@router.get("/transport")
def get_transport(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.get_transport(db, ctx, member_profile_id))


@router.post("/transport")
def post_transport(
    payload: TransportUpdate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.set_transport(db, ctx, payload))


@router.get("/sos")
def get_sos(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_sos(db, ctx))


@router.post("/sos/start")
def post_sos_start(
    payload: SosStart,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.start_sos(db, ctx, payload))


@router.post("/sos/{sos_id}/confirm")
def post_sos_confirm(
    sos_id: str,
    payload: SosConfirm,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.confirm_sos(db, ctx, sos_id, payload))


@router.post("/sos/{sos_id}/acknowledge")
def post_sos_acknowledge(
    sos_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.acknowledge_sos(db, ctx, sos_id))


@router.get("/circle")
def get_circle(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_circle(db, ctx))


@router.get("/circle/caring-for")
def get_caring_for(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_caring_for(db, ctx))


@router.post("/circle/invite")
def post_circle_invite(
    payload: CircleInvite,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.invite_caregiver(db, ctx, payload))


@router.patch("/circle/{link_id}/permissions")
def patch_circle_permissions(
    link_id: str,
    payload: CirclePermissionsUpdate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.update_circle_permissions(db, ctx, link_id, payload.permissions))


@router.post("/circle/{link_id}/revoke")
def post_circle_revoke(
    link_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.revoke_circle(db, ctx, link_id))


@router.get("/alerts")
def get_alerts(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_alerts(db, ctx))


@router.post("/alerts/{alert_id}/acknowledge")
def post_alert_acknowledge(
    alert_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.acknowledge_alert(db, ctx, alert_id))


@router.get("/tasks")
def get_tasks(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_tasks(db, ctx, member_profile_id))


@router.post("/tasks")
def post_task(
    payload: TaskCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_task(db, ctx, payload))


@router.post("/tasks/{task_id}/complete")
def post_task_complete(
    task_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.complete_task(db, ctx, task_id))


@router.get("/handoffs")
def get_handoffs(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_handoffs(db, ctx))


@router.post("/handoffs")
def post_handoff(
    payload: HandoffCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_handoff(db, ctx, payload))


@router.post("/handoffs/{handoff_id}/accept")
def post_handoff_accept(
    handoff_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.resolve_handoff(db, ctx, handoff_id, True))


@router.post("/handoffs/{handoff_id}/decline")
def post_handoff_decline(
    handoff_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.resolve_handoff(db, ctx, handoff_id, False))


@router.get("/coordination")
def get_coordination(
    member_profile_id: str | None = Query(default=None),
    filter: str = Query(default="all"),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.coordination_view(db, ctx, member_profile_id, filter))


@router.post("/ai/converse")
def post_ai_converse(
    payload: AiConverse,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.converse(db, ctx, payload))


@router.post("/ai/orchestrate")
def post_ai_orchestrate(
    payload: AiConverse,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.orchestrate(db, ctx, payload))


@router.get("/transport/requests")
def get_transport_requests(
    member_profile_id: str | None = Query(default=None),
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_transport_requests(db, ctx, member_profile_id))


@router.post("/transport/requests")
def post_transport_request(
    payload: TransportRequestCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_transport_request(db, ctx, payload))


@router.post("/transport/requests/{request_id}/confirm")
def post_transport_confirm(
    request_id: str,
    payload: TransportConfirm,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.confirm_transport_request(db, ctx, request_id, payload))


@router.post("/transport/requests/{request_id}/handoff-simulated")
def post_transport_handoff(
    request_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.simulated_transport_handoff(db, ctx, request_id))


@router.post("/transport/requests/{request_id}/cancel")
def post_transport_cancel(
    request_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.cancel_transport_request(db, ctx, request_id))


@router.get("/notifications")
def get_notifications(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_notifications(db, ctx))


@router.post("/notifications")
def post_notification(
    payload: NotificationQueue,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.queue_notification(db, ctx, payload))


@router.post("/notifications/{notice_id}/simulate-deliver")
def post_notification_deliver(
    notice_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.simulate_notification(db, ctx, notice_id, succeed=True))


@router.post("/notifications/{notice_id}/simulate-fail")
def post_notification_fail(
    notice_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.simulate_notification(db, ctx, notice_id, succeed=False))


@router.post("/notifications/{notice_id}/suppress")
def post_notification_suppress(
    notice_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.suppress_notification(db, ctx, notice_id))


@router.post("/notifications/{notice_id}/retry")
def post_notification_retry(
    notice_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.retry_notification(db, ctx, notice_id))


@router.post("/readings/simulated-device")
def post_simulated_device(
    payload: SimulatedDeviceCreate,
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.create_simulated_device_reading(db, ctx, payload))


@router.get("/audit")
def get_audit(
    ctx: UserContext = Depends(get_current_user_context),
    db: Session = Depends(_db),
):
    return normalize_success(data=service.list_audit(db, ctx))
