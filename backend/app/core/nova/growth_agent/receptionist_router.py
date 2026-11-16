"""Receptionist pilot HTTP routes — calendar OAuth, sync status, notifications, voice.

Live Google/Twilio transports remain default-off. Missing credentials show Not connected.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.growth_agent import calendar_oauth
from app.core.nova.growth_agent import calendar_sync
from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.flags import (
    live_flags,
    voice_simulator_enabled,
)
from app.core.nova.growth_agent.models import (
    GaCalendarSyncJob,
    GaHandoffRequest,
    GaOwnerNotification,
)
from app.core.nova.growth_agent.tenant import require_growth_owner, resolve_org
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/growth-agent",
    tags=["nova-growth-receptionist"],
)


def _org(user: UserContext, organization_id: str | None) -> str:
    try:
        return resolve_org(user, organization_id)
    except GrowthAgentError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc


def _session_fingerprint(user: UserContext, authorization: str | None) -> str:
    raw = f"{user.user_id}|{(authorization or '')[-32:]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class OAuthStartIn(BaseModel):
    organization_id: str | None = None
    redirect_uri: str | None = None


class OAuthCallbackIn(BaseModel):
    organization_id: str | None = None
    state: str
    code: str


class OrgIn(BaseModel):
    organization_id: str | None = None


class HandoffAckIn(BaseModel):
    organization_id: str | None = None


class SelectCalendarIn(BaseModel):
    organization_id: str | None = None
    calendar_id: str = Field(min_length=1, max_length=320)
    calendar_summary: str | None = Field(default=None, max_length=200)


class VoiceSimulatorIn(BaseModel):
    """UI and API agree: called_number/caller_number required; intent/utterance or script."""

    organization_id: str | None = None
    called_number: str = Field(min_length=3, max_length=40)
    caller_number: str = Field(min_length=3, max_length=40)
    intent: str | None = Field(default=None, max_length=64)
    utterance: str | None = Field(default=None, max_length=2000)
    script: list[dict[str, Any]] = Field(default_factory=list)
    simulated: bool = True
    appointment_id: str | None = None
    service_code: str | None = None
    slot_start: str | None = None


@router.get("/receptionist/status")
def receptionist_status(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org = _org(user, organization_id)
    from app.core.nova.growth_agent.readiness import build_readiness

    calendar = calendar_oauth.get_calendar_connection_status(db, org_id=org)
    readiness = build_readiness(db, org_id=org)
    sync_rows = (
        db.query(GaCalendarSyncJob)
        .filter(
            GaCalendarSyncJob.organization_id == org,
            GaCalendarSyncJob.status.in_(("pending", "failed", "running", "stale")),
        )
        .order_by(GaCalendarSyncJob.created_at.desc())
        .limit(25)
        .all()
    )
    notifications = (
        db.query(GaOwnerNotification)
        .filter(GaOwnerNotification.organization_id == org)
        .order_by(GaOwnerNotification.created_at.desc())
        .limit(25)
        .all()
    )
    handoffs = (
        db.query(GaHandoffRequest)
        .filter(GaHandoffRequest.organization_id == org)
        .order_by(GaHandoffRequest.created_at.desc())
        .limit(25)
        .all()
    )
    return {
        "flags": live_flags(),
        "calendar": calendar,
        "sync_errors": [
            {
                "id": row.id,
                "appointment_id": row.appointment_id,
                "action": row.action,
                "status": row.status,
                "operation_version": row.operation_version,
                "last_error_code": row.last_error_code,
                "event_id": row.event_id,
            }
            for row in sync_rows
        ],
        "notifications": [
            {
                "id": row.id,
                "event_type": row.event_type,
                "status": row.status,
                "purpose": row.purpose,
                "error_code": row.error_code,
                "provider_message_id": row.provider_message_id,
            }
            for row in notifications
        ],
        "handoffs": [
            {
                "id": row.id,
                "status": row.status,
                "reason": row.reason,
                "summary": row.summary,
                "channel": row.channel,
                "priority": row.priority,
            }
            for row in handoffs
        ],
        "readiness": readiness,
        "honesty": {
            "internal_booking_is_not_google_confirmation": True,
            "provider_accepted_is_not_inbox_receipt": True,
            "voice_simulator_is_not_live_phone": True,
        },
    }


@router.get("/receptionist/readiness")
def receptionist_readiness(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Owner-only readiness snapshot — no secrets; honest simulated/unverified labels."""
    from app.core.nova.growth_agent.readiness import build_readiness

    org = _org(user, organization_id)
    return build_readiness(db, org_id=org)


@router.post("/calendar/oauth/start")
def calendar_oauth_start(
    body: OAuthStartIn,
    request: Request,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    redirect = body.redirect_uri or str(request.url_for("calendar_oauth_callback_get"))
    # Prefer configured redirect; start_oauth validates exact match.
    import os

    configured = str(os.getenv("NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    result = calendar_oauth.start_oauth(
        db,
        org_id=org,
        owner_user_id=user.user_id,
        session_fingerprint=_session_fingerprint(user, authorization),
        redirect_uri=configured or redirect,
    )
    if result.get("error_code") == "OAUTH_NOT_CONFIGURED":
        return result
    if result.get("error_code"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/calendar/oauth/callback", name="calendar_oauth_callback_get")
def calendar_oauth_callback_get(
    state: str = "",
    code: str = "",
    error: str | None = None,
) -> RedirectResponse:
    """Browser return after Google redirect — never expose tokens in the body.

    Redirects to the owner SPA with ``code`` + ``state`` (or ``oauth_error``) so the
    authenticated page can POST completion. Single-use state remains server-bound;
    the SPA strips query params after the authenticated exchange.
    """
    from urllib.parse import urlencode

    base = "/nova/growth"
    params: dict[str, str] = {"calendar_oauth": "1"}
    if error:
        params["oauth_error"] = str(error)[:200]
        return RedirectResponse(url=f"{base}?{urlencode(params)}", status_code=302)
    if not state or not code:
        params["oauth_error"] = "missing_code_or_state"
        return RedirectResponse(url=f"{base}?{urlencode(params)}", status_code=302)
    params["state"] = state
    params["code"] = code
    return RedirectResponse(url=f"{base}?{urlencode(params)}", status_code=302)


@router.post("/calendar/oauth/callback")
def calendar_oauth_callback_post(
    body: OAuthCallbackIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    result = calendar_oauth.complete_oauth(
        db,
        org_id=org,
        owner_user_id=user.user_id,
        session_fingerprint=_session_fingerprint(user, authorization),
        state=body.state,
        code=body.code,
    )
    if result.get("error_code") and result.get("status") == "Not connected":
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/calendar/disconnect")
def calendar_disconnect(
    body: OrgIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org = _org(user, body.organization_id)
    return calendar_oauth.disconnect_calendar(db, org_id=org, owner_user_id=user.user_id)


@router.get("/calendar/list")
def calendar_list(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List calendars for the connected org (injectable/live-gated; no tokens returned)."""
    from app.core.nova.growth_agent import calendar_credentials as creds

    org = _org(user, organization_id)
    return creds.list_calendars_for_org(db, org_id=org)


@router.post("/calendar/select")
def calendar_select(
    body: SelectCalendarIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Persist selected calendar id after OAuth. Does not enable live Google writes."""
    from app.core.nova.growth_agent import calendar_credentials as creds

    org = _org(user, body.organization_id)
    result = creds.select_calendar(
        db,
        org_id=org,
        owner_user_id=user.user_id,
        calendar_id=body.calendar_id,
        calendar_summary=body.calendar_summary,
    )
    if result.get("error_code") in {"CALENDAR_NOT_CONNECTED", "OWNER_MISMATCH", "INVALID_CALENDAR_ID"}:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/calendar/sync-errors")
def calendar_sync_errors(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org = _org(user, organization_id)
    rows = (
        db.query(GaCalendarSyncJob)
        .filter(
            GaCalendarSyncJob.organization_id == org,
            GaCalendarSyncJob.status.in_(("pending", "failed", "stale", "running")),
        )
        .order_by(GaCalendarSyncJob.updated_at.desc())
        .limit(50)
        .all()
    )
    return {"jobs": [calendar_sync._job_dict(row) for row in rows]}


@router.post("/calendar/sync/tick")
def calendar_sync_tick(
    body: OrgIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Process pending sync jobs with injected/mock transport. Live writes hard-off."""
    from app.core.nova.growth_agent.flags import calendar_sync_worker_enabled
    from app.core.nova.growth_agent.providers.google_calendar_transport import (
        GoogleCalendarTransport,
    )

    if not calendar_sync_worker_enabled():
        raise HTTPException(status_code=404, detail="Calendar sync worker disabled")
    org = _org(user, body.organization_id)
    from app.core.nova.growth_agent.calendar_credentials import access_token_provider_for

    # Token provider is wired so injected http clients can authorize; live writes stay hard-off.
    transport = GoogleCalendarTransport(get_access_token=access_token_provider_for(db))
    results = calendar_sync.process_sync_batch(
        db,
        worker_id=f"owner-tick-{user.user_id[:8]}",
        limit=20,
        transport=transport,
        organization_id=org,
    )
    return {"processed": results, "live": False}


@router.post("/notifications/tick")
def notifications_tick(
    body: OrgIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Process transactional owner notifications via mock adapter. Live email hard-off."""
    from app.core.nova.growth_agent import owner_notifications as on
    from app.core.nova.growth_agent.flags import owner_notification_worker_enabled
    from app.core.nova.growth_agent.providers.mock_email import MockEmailAdapter

    if not owner_notification_worker_enabled():
        raise HTTPException(status_code=404, detail="Owner notification worker disabled")
    _org(user, body.organization_id)
    result = on.process_owner_notifications(
        db,
        worker_id=f"owner-notify-{user.user_id[:8]}",
        limit=20,
        email_adapter=MockEmailAdapter(),
    )
    db.commit()
    result["honesty"] = {"provider_accepted_is_not_inbox_receipt": True}
    result["live"] = False
    return result


@router.get("/notifications")
def list_notifications(
    organization_id: str | None = None,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.core.nova.growth_agent import owner_notifications as on

    org = _org(user, organization_id)
    return {
        "notifications": on.list_owner_notifications(db, org),
        "honesty": {"provider_accepted_is_not_inbox_receipt": True},
    }


@router.get("/handoffs")
def list_handoffs(
    organization_id: str | None = None,
    status: str | None = Query(default=None),
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.core.nova.growth_agent import handoff_queue as hq

    org = _org(user, organization_id)
    return {"handoffs": hq.list_handoffs(db, org, status=status)}


@router.post("/handoffs/{handoff_id}/acknowledge")
def acknowledge_handoff(
    handoff_id: str,
    body: HandoffAckIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.core.nova.growth_agent import handoff_queue as hq
    from app.core.nova.growth_agent.errors import GrowthAgentError as GAErr

    org = _org(user, body.organization_id)
    try:
        result = hq.acknowledge_handoff(db, org, handoff_id, user.user_id)
        db.commit()
        return result
    except GAErr as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.as_dict()) from exc


@router.post("/voice/simulator/run")
def voice_simulator_run(
    body: VoiceSimulatorIn,
    user: UserContext = Depends(require_growth_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Owner-only voice path simulator — never hits Twilio or places calls.

    Accepts either a multi-step ``script`` or a single ``intent``/``utterance`` turn
    (as sent by receptionist.js). Routes through ServiceBackedGrowthVoiceOps →
    real FAQ / lead / availability / booking / notify / handoff services.
    """
    if not voice_simulator_enabled():
        raise HTTPException(
            status_code=404,
            detail="Voice simulator disabled (set NOVA_GROWTH_AGENT_VOICE_SIMULATOR=true)",
        )
    org = _org(user, body.organization_id)
    from uuid import uuid4

    from app.core.nova.growth_agent.models import GaVoiceAgentMapping
    from app.core.nova.growth_agent.voice import simulator as sim
    from app.core.nova.growth_agent.voice.inbound import normalize_e164
    from app.core.nova.growth_agent.voice.ops import (
        ServiceBackedGrowthVoiceOps,
        intent_to_event_type,
    )

    called = normalize_e164(body.called_number)
    mapping = (
        db.query(GaVoiceAgentMapping)
        .filter_by(provider="twilio", external_number=called)
        .one_or_none()
    )
    if mapping is None:
        mapping = GaVoiceAgentMapping(
            id=uuid4().hex,
            organization_id=org,
            provider="twilio",
            external_number=called,
            agent_label="receptionist-simulator",
            active=True,
            kill_switch=False,
            daily_call_limit=100,
            meta_json={"simulated": True},
        )
        db.add(mapping)
        db.flush()
    elif mapping.organization_id != org:
        raise HTTPException(status_code=403, detail="Called number mapped to another tenant")

    steps = list(body.script or [])
    if not steps:
        event_type = intent_to_event_type(body.intent, body.utterance)
        step: dict[str, Any] = {
            "event_type": event_type,
            "from_number": body.caller_number,
            "question": body.utterance or body.intent or "",
            "SpeechResult": body.utterance or "",
        }
        if body.appointment_id:
            step["appointment_id"] = body.appointment_id
        if body.service_code:
            step["service_code"] = body.service_code
        if body.slot_start:
            step["slot_start"] = body.slot_start
        # Auto-chain lead capture before book when UI asks to book in one click
        if event_type == "book":
            steps = [
                {
                    "event_type": "capture_lead",
                    "from_number": body.caller_number,
                    "caller_name": "Simulator caller",
                },
                step,
            ]
        elif event_type == "faq_answer":
            steps = [step]
        else:
            steps = [step]

    for step in steps:
        step.setdefault("from_number", body.caller_number)

    ops = ServiceBackedGrowthVoiceOps(db, actor_user_id=user.user_id)
    outcomes = sim.run_labeled_simulator_journey(
        db,
        url="https://example.invalid/api/nova/growth-agent/voice/twilio/webhook",
        to_number=body.called_number,
        growth_ops=ops,  # type: ignore[arg-type]
        steps=steps,
    )
    db.commit()
    return {
        "simulated": True,
        "live_phone": False,
        "label": "SIMULATED — not proof of live phone operation",
        "organization_id": org,
        "intent": body.intent,
        "utterance": body.utterance,
        "outcomes": outcomes,
    }


@router.post("/voice/twilio/webhook")
async def twilio_voice_webhook(request: Request, db: Session = Depends(get_db)) -> PlainTextResponse:
    """Twilio inbound webhook. Live voice hard-off; signature validated when configured."""
    import os

    from app.core.nova.growth_agent.errors import GrowthAgentError as GAErr
    from app.core.nova.growth_agent.flags import REAL_VOICE
    from app.core.nova.growth_agent.voice.inbound import receive_inbound_webhook

    form = {str(k): str(v) for k, v in (await request.form()).items()}
    signature = request.headers.get("X-Twilio-Signature", "")
    from app.core.nova.growth_agent.voice.twilio_signature import public_request_url

    # Twilio signs the public URL (scheme/host as seen by Twilio), not the internal proxy URL.
    url = public_request_url(
        request_url=str(request.url),
        headers={k: v for k, v in request.headers.items()},
    )
    auth_token = str(os.getenv("TWILIO_AUTH_TOKEN") or "").strip() or None
    # Public webhook: never honor unsigned simulation shortcuts. Simulator mode only
    # when the voice simulator flag is on AND the caller already presents a signature
    # that will be validated (owner-labeled helpers use SIMULATOR_AUTH).
    wants_sim = str(form.get("simulated") or "").lower() in {"1", "true", "yes"}
    simulator_mode = bool(wants_sim and voice_simulator_enabled() and signature)
    if wants_sim and not voice_simulator_enabled():
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?><Response><Reject/></Response>',
            media_type="application/xml",
            status_code=403,
        )

    # Hard-off: never process as live telephony.
    if REAL_VOICE:
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?><Response><Say>Live voice is disabled.</Say></Response>',
            media_type="application/xml",
            status_code=503,
        )

    class _RejectOps:
        def faq_answer(self, *, organization_id: str, question: str) -> dict[str, Any]:
            return {
                "answer": "Receptionist is in simulation-only mode.",
                "organization_id": organization_id,
                "question": question,
                "live": False,
            }

        def capture_lead(
            self,
            *,
            organization_id: str,
            phone: str | None,
            name: str | None,
            notes: str | None,
        ) -> dict[str, Any]:
            raise GAErr("VOICE_LIVE_DISABLED", "Live lead capture via phone is disabled", http_status=503)

        def check_availability(
            self, *, organization_id: str, service_code: str | None
        ) -> dict[str, Any]:
            raise GAErr("VOICE_LIVE_DISABLED", "Live availability via phone is disabled", http_status=503)

        def book(
            self,
            *,
            organization_id: str,
            contact_id: str | None,
            service_code: str,
            slot_start: str,
        ) -> dict[str, Any]:
            raise GAErr("VOICE_LIVE_DISABLED", "Live booking via phone is disabled", http_status=503)

        def reschedule(
            self, *, organization_id: str, appointment_id: str, slot_start: str
        ) -> dict[str, Any]:
            raise GAErr("VOICE_LIVE_DISABLED", "Live reschedule via phone is disabled", http_status=503)

        def cancel(self, *, organization_id: str, appointment_id: str) -> dict[str, Any]:
            raise GAErr("VOICE_LIVE_DISABLED", "Live cancel via phone is disabled", http_status=503)

        def create_handoff(
            self,
            *,
            organization_id: str,
            contact_id: str | None,
            reason: str,
            summary: str,
        ) -> dict[str, Any]:
            from app.core.nova.growth_agent import handoff_queue as hq

            row = hq.create_handoff(
                db,
                org_id=organization_id,
                reason=reason or "inbound_voice_escalation",
                summary=summary or "Inbound voice requested human help (live calling still disabled)",
                channel="voice",
                contact_id=contact_id,
            )
            db.flush()
            return row

    try:
        result = receive_inbound_webhook(
            db,
            url=url,
            params=form,
            signature_header=signature,
            auth_token=auth_token,
            growth_ops=_RejectOps(),  # type: ignore[arg-type]
            simulator_mode=simulator_mode and voice_simulator_enabled(),
        )
        db.commit()
    except GAErr as exc:
        return PlainTextResponse(
            f'<?xml version="1.0" encoding="UTF-8"?><Response><Say>{exc.message}</Say><Reject/></Response>',
            media_type="application/xml",
            status_code=int(exc.http_status or 403),
        )
    except Exception:
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?><Response><Reject/></Response>',
            media_type="application/xml",
            status_code=403,
        )

    say = "Receptionist request recorded."
    if result.get("status") == "duplicate":
        say = "Duplicate event ignored."
    return PlainTextResponse(
        f'<?xml version="1.0" encoding="UTF-8"?><Response><Say>{say}</Say></Response>',
        media_type="application/xml",
    )
