"""Sandbox Casting pilot rules. No network, storage, or outbound delivery.

Callers pass plain mappings and an actor resolved from the Nova session.
Protected-trait fields are rejected. Nothing in this module casts a person,
signs a URL, or marks a message delivered.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MINIMUM_AGE = 18
MAX_RETENTION_DAYS = 365
DEFAULT_RETENTION_DAYS = 30
MESSAGE_DAILY_LIMIT = 20
PAGE_LIMIT = 50
RETENTION_NOTICE = (
    "Sandbox consent: this test application is kept only for the retention window "
    "you select, up to 365 days. You may revoke consent, which clears the contact "
    "details and audition link from review. This is not a public audition, and "
    "AMICOR does not send the application to a studio or messaging provider."
)
REVIEW_STAGES = frozenset({"New", "In review", "Callback", "Closed"})
MESSAGE_KINDS = frozenset({"confirmation", "invite", "reminder", "update"})
RUBRIC_CRITERIA = frozenset({
    "preparation", "clarity", "reliability", "instructions_followed",
})
PROTECTED_FIELDS = frozenset({
    "race", "ethnicity", "religion", "gender", "sex", "disability",
    "sexual_orientation", "national_origin", "political_affiliation",
    "facial_score", "guardian_attestation", "genetic", "health_status",
    "pregnancy", "age_score", "beauty_score", "skin_tone", "caste",
})
SAFE_REASONS = frozenset({
    "Unsupported field",
    "Invalid role",
    "Invalid title",
    "Deadline required",
    "Deadline passed",
    "Consent required",
    "Consent version required",
    "Consent expired",
    "Consent revoked",
    "Applicant does not meet the minimum age",
    "Duplicate application",
    "Invalid video link",
    "Invalid email",
    "Invalid name",
    "Eligibility required",
    "Rate limited",
    "Idempotency key required",
    "SMS is not configured",
    "WhatsApp is not configured",
    "Outbound disabled",
    "Expired invite",
    "Invalid timezone",
    "Invalid schedule",
    "Invalid review",
    "Request rejected",
    "Suppressed",
    "Campaign cannot be published",
    "Rejected by security scan",
    "Unsupported video type",
    "Invalid video size",
})
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,24}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'-]{0,78}$")
_QUESTION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_ROLE_FIELDS = frozenset({"title", "requirements", "deadline", "minimum_age", "questions"})
_INTAKE_FIELDS = frozenset({
    "role_id", "display_name", "contact_email", "video_url", "age_years",
    "consent_accepted", "consent_version", "retention_days", "answers",
})
_BLOCKED_SCHEMES = ("javascript:", "data:", "file:", "blob:", "vbscript:")


class PilotRejected(ValueError):
    """A safe, caller-visible validation failure. No database text."""


class PilotDenied(PermissionError):
    """The actor cannot see or change this sandbox record."""


@dataclass(frozen=True)
class PilotDecision:
    accepted: bool
    reason: str


def _reject(reason: str) -> PilotDecision:
    return PilotDecision(False, reason)


def _protected(payload: Mapping) -> bool:
    for key in payload:
        if str(key).strip().lower() in PROTECTED_FIELDS:
            return True
    return False


def _clean_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit:
        return None
    if any(ord(char) < 32 or char in "<>" for char in text):
        return None
    return text


def validate_https_url(value: object) -> PilotDecision:
    """Accept only a credential-free https URL. No IP hosts and no script schemes."""
    if not isinstance(value, str):
        return _reject("Invalid video link")
    text = value.strip()
    if not text or len(text) > 500 or any(ord(char) < 32 or char in '<>"\'' for char in text):
        return _reject("Invalid video link")
    lowered = text.lower()
    if lowered.startswith(_BLOCKED_SCHEMES) or "\\" in text:
        return _reject("Invalid video link")
    parts = urlsplit(text)
    if parts.scheme != "https" or parts.username or parts.password:
        return _reject("Invalid video link")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".local") or "." not in host:
        return _reject("Invalid video link")
    try:
        ip_address(host)
    except ValueError:
        return PilotDecision(True, "Link accepted; no file was stored")
    return _reject("Invalid video link")


def validate_role(payload: Mapping) -> PilotDecision:
    if not isinstance(payload, Mapping) or _protected(payload):
        return _reject("Unsupported field")
    if set(payload) - _ROLE_FIELDS:
        return _reject("Unsupported field")
    title = _clean_text(payload.get("title"), limit=80)
    if title is None:
        return _reject("Invalid title")
    requirements = payload.get("requirements", "")
    if requirements != "" and _clean_text(requirements, limit=2000) is None:
        return _reject("Invalid role")
    deadline = _parse_time(payload.get("deadline"))
    if deadline is None:
        return _reject("Deadline required")
    minimum_age = payload.get("minimum_age", MINIMUM_AGE)
    if isinstance(minimum_age, bool) or not isinstance(minimum_age, int) or minimum_age < MINIMUM_AGE:
        return _reject("Applicant does not meet the minimum age")
    questions = payload.get("questions", [])
    if not isinstance(questions, list) or len(questions) > 8:
        return _reject("Invalid role")
    seen = set()
    for item in questions:
        if not isinstance(item, Mapping) or set(item) - {"id", "prompt"} or _protected(item):
            return _reject("Unsupported field")
        question_id = item.get("id")
        prompt = _clean_text(item.get("prompt"), limit=200)
        if not isinstance(question_id, str) or _QUESTION_ID.fullmatch(question_id) is None or prompt is None:
            return _reject("Invalid role")
        if question_id in seen:
            return _reject("Invalid role")
        seen.add(question_id)
    return PilotDecision(True, "Role accepted; the campaign stays unpublished")


def normalize_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if len(text) > 320 or _EMAIL.fullmatch(text) is None:
        return None
    return text


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def receipt_code(application_id: str) -> str:
    compact = "".join(char for char in application_id.upper() if char.isalnum())
    return "CA-" + (compact[:10] or "DRAFT").ljust(10, "0")


def sample_harborlight_plan() -> dict:
    """Fictional 30-day pilot. Not a customer, contract, or partnership."""
    return {
        "label": "Demo / Early Access",
        "title": "Harborlight",
        "category": "film",
        "summary": (
            "Fictional 30-day limited-series casting window for an independent "
            "production. Every person, link, and message in the sample is invented."
        ),
        "window": {"starts": "2026-11-01T15:00:00+00:00", "ends": "2026-12-01T15:00:00+00:00"},
        "roles": [
            {
                "title": "Harbor lead",
                "requirements": "A two-minute self-tape with a short side. Adults only.",
                "deadline": "2026-11-07T23:00:00+00:00",
                "minimum_age": 18,
                "questions": [{"id": "union", "prompt": "Are you able to attend a sandbox callback?"}],
            },
            {
                "title": "Night clerk",
                "requirements": "One scene, indoors, no special effects.",
                "deadline": "2026-11-07T23:00:00+00:00",
                "minimum_age": 18,
                "questions": [{"id": "union", "prompt": "Are you able to attend a sandbox callback?"}],
            },
            {
                "title": "Background reader",
                "requirements": "Read a half page on camera. No travel is required.",
                "deadline": "2026-11-07T23:00:00+00:00",
                "minimum_age": 18,
                "questions": [],
            },
        ],
        "timeline": [
            {"day": 1, "step": "Organizer opens an unpublished campaign and three roles."},
            {"day": 3, "step": "Participants save drafts with consent and https audition links."},
            {"day": 7, "step": "Deadline. Duplicate and under-18 submissions are rejected."},
            {"day": 10, "step": "A person shortlists. Scores never cast someone automatically."},
            {"day": 14, "step": "Organizer approves a callback draft. It is not sent."},
            {"day": 18, "step": "Call sheet is shown in America/New_York."},
            {"day": 21, "step": "One participant revokes consent and the reminder is suppressed."},
            {"day": 30, "step": "Organizer exports a minimized CSV. The campaign stays unpublished."},
        ],
        "offer": {
            "name": "30-day Casting and Auditions sandbox pilot",
            "amount_usd": 2400,
            "currency": "USD",
            "sample": True,
            "contract": False,
            "scope": (
                "One production, up to 3 roles, consent-based sandbox intake, human review, "
                "and message previews that do not send. Public intake, paid ads, and "
                "distribution are outside this sample offer."
            ),
        },
        "audience": "Independent producers and online creators",
        "partnerships": [],
        "capability": (
            "AMICOR can demonstrate organization-scoped campaigns, adult consent, "
            "audition links, human shortlists, approval-gated email drafts, and "
            "timezone call sheets. It does not claim a studio, streaming, or prior-customer relationship."
        ),
    }


def _organizer(actor: Mapping) -> bool:
    return bool(
        actor.get("user_id")
        and actor.get("verified") is True
        and actor.get("role") == "organizer"
        and actor.get("organization_id")
    )


def _reviewer(actor: Mapping) -> bool:
    return bool(
        actor.get("user_id")
        and actor.get("verified") is True
        and actor.get("role") in {"organizer", "reviewer"}
        and actor.get("organization_id")
    )


def _same_org(actor: Mapping, organization_id: str) -> bool:
    return actor.get("organization_id") == organization_id


class PilotDirectory:
    """In-memory sandbox workflow. The SQL store loads and saves this shape."""

    def __init__(self, now: datetime, id_factory=None):
        self.now = _as_utc(now)
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self.roles: dict[str, dict] = {}
        self.intakes: dict[str, dict] = {}
        self.rubrics: list[dict] = []
        self.messages: dict[str, dict] = {}
        self.suppressions: dict[tuple[str, str], dict] = {}
        self.schedules: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.campaigns: dict[str, dict] = {}
        self.invites: dict[str, dict] = {}
        self.mock_attempts: dict[str, dict] = {}
        self.mock_media: dict[str, dict] = {}
        self.journey_audit: list[dict] = []
        self.changed = False

    def _new_id(self) -> str:
        return str(self._id_factory())

    def _audit(self, actor: Mapping, action: str, object_id: str) -> None:
        self.audit.append({
            "id": self._new_id(),
            "actor_id": actor["user_id"],
            "organization_id": actor["organization_id"],
            "action": action,
            "object_id": object_id,
            "occurred_at": self.now.isoformat(),
        })
        self.changed = True

    def _journey(self, actor: Mapping, action: str, object_id: str) -> None:
        self.journey_audit.append({
            "id": self._new_id(),
            "actor_id": actor["user_id"],
            "organization_id": actor["organization_id"],
            "action": action,
            "object_id": object_id,
            "occurred_at": self.now.isoformat(),
        })
        self.changed = True

    def note_campaign(self, *, organization_id: str, tenant_id: str, campaign_id: str, status: str) -> None:
        """Remember a campaign loaded from the sandbox tables. This does not publish it."""
        safe = status if status in {"DRAFT", "CLOSED"} else "CLOSED"
        self.campaigns[campaign_id] = {
            "id": campaign_id,
            "organization_id": organization_id,
            "tenant_id": tenant_id,
            "status": safe,
            "published": False,
        }

    def create_role(self, actor: Mapping, campaign_id: str, payload: Mapping) -> dict:
        if not _organizer(actor) or not _same_org(actor, actor["organization_id"]):
            raise PilotDenied("Campaign unavailable")
        campaign = self.campaigns.get(campaign_id)
        if campaign is not None:
            if campaign["organization_id"] != actor["organization_id"]:
                raise PilotDenied("Campaign unavailable")
            if campaign.get("tenant_id") and actor.get("tenant_id") and campaign["tenant_id"] != actor["tenant_id"]:
                raise PilotDenied("Campaign unavailable")
            if campaign["status"] != "DRAFT" or campaign.get("published"):
                raise PilotRejected("Campaign cannot be published")
        decision = validate_role(payload)
        if not decision.accepted:
            raise PilotRejected(decision.reason)
        title = _clean_text(payload["title"], limit=80)
        if any(row["campaign_id"] == campaign_id and row["title"].lower() == title.lower()
               and row["organization_id"] == actor["organization_id"] for row in self.roles.values()):
            raise PilotRejected("Invalid role")
        questions = [
            {"id": item["id"], "prompt": _clean_text(item["prompt"], limit=200)}
            for item in payload.get("questions", [])
        ]
        role_id = self._new_id()
        record = {
            "id": role_id,
            "organization_id": actor["organization_id"],
            "campaign_id": campaign_id,
            "title": title,
            "requirements": _clean_text(payload.get("requirements", "") or "None", limit=2000) if payload.get("requirements") else "",
            "deadline": _parse_time(payload["deadline"]).isoformat(),
            "minimum_age": int(payload.get("minimum_age", MINIMUM_AGE)),
            "questions": questions,
            "created_at": self.now.isoformat(),
            "published": False,
        }
        if payload.get("requirements"):
            record["requirements"] = _clean_text(payload["requirements"], limit=2000)
        self.roles[role_id] = record
        self._audit(actor, "role.created", role_id)
        return _role_view(record)

    def list_roles(self, actor: Mapping, campaign_id: str, limit: int = 20, offset: int = 0) -> dict:
        if not _reviewer(actor):
            raise PilotDenied("Campaign unavailable")
        rows = [
            _role_view(row) for row in self.roles.values()
            if row["organization_id"] == actor["organization_id"] and row["campaign_id"] == campaign_id
        ]
        rows.sort(key=lambda item: (item["created_at"], item["id"]))
        return _page(rows, limit, offset)

    def save_intake(self, actor: Mapping, *, application_id: str, campaign_id: str, payload: Mapping) -> dict:
        if actor.get("role") != "applicant" or not actor.get("user_id"):
            raise PilotDenied("Application unavailable")
        if not isinstance(payload, Mapping) or _protected(payload) or set(payload) - _INTAKE_FIELDS:
            raise PilotRejected("Unsupported field")
        role = self.roles.get(str(payload.get("role_id") or ""))
        if role is None or role["organization_id"] != actor["organization_id"] or role["campaign_id"] != campaign_id:
            raise PilotDenied("Application unavailable")
        existing = self.intakes.get(application_id)
        if existing is not None:
            if existing["applicant_id"] != actor["user_id"] or existing["organization_id"] != actor["organization_id"]:
                raise PilotDenied("Application unavailable")
            if existing["consent_revoked_at"]:
                raise PilotRejected("Consent revoked")
            if existing["status"] != "DRAFT":
                return _applicant_view(existing)
        built = _build_intake(
            actor=actor, application_id=application_id, campaign_id=campaign_id,
            role=role, payload=payload, now=self.now, existing=existing,
        )
        if built is None:
            raise PilotRejected(_intake_error(role, payload))
        email = built["contact_email"]
        for other in self.intakes.values():
            if other["id"] == application_id:
                continue
            if other["organization_id"] != actor["organization_id"]:
                continue
            if other["campaign_id"] == campaign_id and other["role_id"] == role["id"] and other["contact_email"] == email and other["status"] != "WITHDRAWN":
                raise PilotRejected("Duplicate application")
            if other["campaign_id"] == campaign_id and other["applicant_id"] == actor["user_id"] and other["role_id"] == role["id"] and other["status"] != "WITHDRAWN":
                raise PilotRejected("Duplicate application")
        self.intakes[application_id] = built
        self._audit(actor, "intake.saved", application_id)
        return _applicant_view(built)

    def submit_intake(self, actor: Mapping, application_id: str) -> dict:
        row = self._own_intake(actor, application_id)
        if row["consent_revoked_at"]:
            raise PilotRejected("Consent revoked")
        if row["status"] == "SUBMITTED":
            return _applicant_view(row)
        if row["status"] != "DRAFT":
            raise PilotDenied("Application unavailable")
        role = self.roles[row["role_id"]]
        reason = _submit_block(row, role, self.now)
        if reason:
            raise PilotRejected(reason)
        row["status"] = "SUBMITTED"
        row["updated_at"] = self.now.isoformat()
        self._audit(actor, "intake.submitted", application_id)
        return _applicant_view(row)

    def revoke_intake(self, actor: Mapping, application_id: str) -> dict:
        row = self._own_intake(actor, application_id)
        _clear_contact(row)
        row["consent_revoked_at"] = self.now.isoformat()
        row["status"] = "WITHDRAWN"
        row["shortlisted"] = False
        row["updated_at"] = self.now.isoformat()
        self._audit(actor, "consent.revoked", application_id)
        return _applicant_view(row)

    def minimize_intake(self, actor: Mapping, application_id: str) -> dict:
        row = self.intakes.get(application_id)
        if row is None or row["organization_id"] != actor.get("organization_id"):
            raise PilotDenied("Application unavailable")
        allowed = actor.get("user_id") == row["applicant_id"] or _organizer(actor)
        if not allowed:
            raise PilotDenied("Application unavailable")
        _clear_contact(row)
        row["minimized"] = True
        row["updated_at"] = self.now.isoformat()
        self._audit(actor, "intake.minimized", application_id)
        return _applicant_view(row) if actor.get("role") == "applicant" else _organizer_view(row)

    def queue(self, actor: Mapping, *, query: str = "", status: str = "", shortlisted: str = "",
              limit: int = 20, offset: int = 0) -> dict:
        if not _reviewer(actor):
            raise PilotDenied("Application unavailable")
        limit, offset = _bounds(limit, offset)
        needle = query.strip().lower()
        rows = []
        for row in self.intakes.values():
            if row["organization_id"] != actor["organization_id"]:
                continue
            if status and row["status"] != status:
                continue
            if shortlisted == "true" and not row["shortlisted"]:
                continue
            if shortlisted == "false" and row["shortlisted"]:
                continue
            if needle and needle not in _search_blob(row, self.roles).lower():
                continue
            view = _organizer_view(row) if actor.get("role") == "organizer" else _reviewer_view(row)
            view["role_title"] = self.roles.get(row["role_id"], {}).get("title", "")
            rows.append(view)
        rows.sort(key=lambda item: (item["created_at"], item["id"]))
        return _page(rows, limit, offset)

    def set_review(self, actor: Mapping, application_id: str, *, stage: str, shortlisted: bool) -> dict:
        if not _reviewer(actor):
            raise PilotDenied("Application unavailable")
        if stage not in REVIEW_STAGES or not isinstance(shortlisted, bool):
            raise PilotRejected("Invalid review")
        row = self.intakes.get(application_id)
        if row is None or row["organization_id"] != actor["organization_id"] or row["status"] != "SUBMITTED":
            raise PilotDenied("Application unavailable")
        if row["consent_revoked_at"]:
            raise PilotRejected("Consent revoked")
        row["stage"] = stage
        row["shortlisted"] = shortlisted
        row["updated_at"] = self.now.isoformat()
        self._audit(actor, "review.updated", application_id)
        view = _organizer_view(row) if actor.get("role") == "organizer" else _reviewer_view(row)
        view["decision"] = "human_required"
        view["automatic_cast"] = False
        return view

    def add_rubric(self, actor: Mapping, application_id: str, payload: Mapping) -> dict:
        if not _reviewer(actor):
            raise PilotDenied("Application unavailable")
        if not isinstance(payload, Mapping) or set(payload) - {"criterion", "score", "comment"} or _protected(payload):
            raise PilotRejected("Unsupported field")
        criterion = payload.get("criterion")
        score = payload.get("score")
        comment = payload.get("comment", "")
        if criterion not in RUBRIC_CRITERIA:
            raise PilotRejected("Invalid review")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise PilotRejected("Invalid review")
        if comment != "" and _clean_text(comment, limit=1000) is None:
            raise PilotRejected("Invalid review")
        row = self.intakes.get(application_id)
        if row is None or row["organization_id"] != actor["organization_id"] or row["status"] != "SUBMITTED":
            raise PilotDenied("Application unavailable")
        note = {
            "id": self._new_id(),
            "organization_id": actor["organization_id"],
            "application_id": application_id,
            "reviewer_id": actor["user_id"],
            "criterion": criterion,
            "score": score,
            "comment": "" if comment == "" else _clean_text(comment, limit=1000),
            "updated_at": self.now.isoformat(),
            "automatic_cast": False,
        }
        self.rubrics = [
            item for item in self.rubrics
            if not (item["application_id"] == application_id and item["reviewer_id"] == actor["user_id"] and item["criterion"] == criterion)
        ]
        self.rubrics.append(note)
        self._audit(actor, "rubric.recorded", application_id)
        return {
            "application_id": application_id,
            "reviewer_id": actor["user_id"],
            "criterion": criterion,
            "score": score,
            "comment": note["comment"],
            "automatic_cast": False,
            "decision": "human_required",
        }

    def draft_message(self, actor: Mapping, payload: Mapping, *, sms_configured: bool = False,
                      whatsapp_configured: bool = False) -> dict:
        if not _organizer(actor):
            raise PilotDenied("Application unavailable")
        if not isinstance(payload, Mapping) or _protected(payload):
            raise PilotRejected("Unsupported field")
        kind = payload.get("kind")
        channel = payload.get("channel", "email")
        key = payload.get("idempotency_key")
        if kind not in MESSAGE_KINDS:
            raise PilotRejected("Request rejected")
        if not isinstance(key, str) or _IDEMPOTENCY.fullmatch(key) is None:
            raise PilotRejected("Idempotency key required")
        existing = next((item for item in self.messages.values()
                         if item["organization_id"] == actor["organization_id"] and item["idempotency_key"] == key), None)
        if existing is not None:
            return _message_view(existing)
        if self._messages_today(actor["organization_id"]) >= MESSAGE_DAILY_LIMIT:
            raise PilotRejected("Rate limited")
        application_id = str(payload.get("application_id") or "")
        intake = self.intakes.get(application_id) if application_id else None
        if application_id and (intake is None or intake["organization_id"] != actor["organization_id"]):
            raise PilotDenied("Application unavailable")
        suppressed = False
        if intake is not None and (intake["consent_revoked_at"] or intake["contact_email"] == ""):
            suppressed = True
        if intake is not None and (actor["organization_id"], intake["contact_email"]) in self.suppressions:
            suppressed = True
        channel_status, status = _channel_status(
            channel=channel, suppressed=suppressed, sms_configured=sms_configured,
            whatsapp_configured=whatsapp_configured,
        )
        if channel_status in {"SMS is not configured", "WhatsApp is not configured"}:
            raise PilotRejected(channel_status)
        role_title = ""
        receipt = ""
        if intake is not None:
            role_title = self.roles.get(intake["role_id"], {}).get("title", "")
            receipt = intake["receipt"]
        when = ""
        if intake is not None and intake["role_id"] in self.schedules:
            when = self.schedules[intake["role_id"]]["starts_at"]
        message_id = self._new_id()
        record = {
            "id": message_id,
            "organization_id": actor["organization_id"],
            "application_id": application_id,
            "kind": kind,
            "channel": channel if channel in {"email", "sms", "whatsapp"} else "email",
            "body": _render_message(kind, receipt=receipt, role_title=role_title, when=when),
            "status": "suppressed" if suppressed else status,
            "idempotency_key": key,
            "attempt_count": 0,
            "approved_by": "",
            "delivery_state": "not_sent",
            "external_delivery": False,
            "delivered": False,
            "created_at": self.now.isoformat(),
            "updated_at": self.now.isoformat(),
        }
        if channel in {"sms", "whatsapp"}:
            record["status"] = "failed_closed"
        self.messages[message_id] = record
        self._audit(actor, "message.drafted", message_id)
        return _message_view(record)

    def approve_message(self, actor: Mapping, message_id: str) -> dict:
        if not _organizer(actor):
            raise PilotDenied("Application unavailable")
        record = self.messages.get(message_id)
        if record is None or record["organization_id"] != actor["organization_id"]:
            raise PilotDenied("Application unavailable")
        intake = self.intakes.get(record["application_id"]) if record["application_id"] else None
        if record["status"] == "suppressed" or (intake is not None and intake["consent_revoked_at"]):
            record["status"] = "suppressed"
        elif _invite_expired(self, intake):
            record["status"] = "failed_closed"
            record["body"] = record["body"] + " Expired invite. Nothing was sent."
        elif record["status"] == "draft":
            record["status"] = "approved"
            record["approved_by"] = actor["user_id"]
        record["delivery_state"] = "not_sent"
        record["external_delivery"] = False
        record["delivered"] = False
        record["updated_at"] = self.now.isoformat()
        self._audit(actor, "message.approved", message_id)
        return _message_view(record)

    def retry_message(self, actor: Mapping, message_id: str) -> dict:
        if not _organizer(actor):
            raise PilotDenied("Application unavailable")
        record = self.messages.get(message_id)
        if record is None or record["organization_id"] != actor["organization_id"]:
            raise PilotDenied("Application unavailable")
        record["attempt_count"] = int(record["attempt_count"]) + 1
        if record["status"] == "draft":
            record["status"] = "failed_closed"
        record["delivery_state"] = "not_sent"
        record["external_delivery"] = False
        record["delivered"] = False
        record["updated_at"] = self.now.isoformat()
        self._audit(actor, "message.retried", message_id)
        return _message_view(record)

    def suppress(self, actor: Mapping, payload: Mapping) -> dict:
        if not _organizer(actor) and actor.get("role") != "applicant":
            raise PilotDenied("Application unavailable")
        reason = payload.get("reason") if isinstance(payload, Mapping) else None
        if reason not in {"stop", "unsubscribe"}:
            raise PilotRejected("Request rejected")
        email = normalize_email(payload.get("contact_email"))
        if email is None:
            raise PilotRejected("Invalid email")
        if actor.get("role") == "applicant":
            owned = any(row["applicant_id"] == actor["user_id"] and row["contact_email"] == email for row in self.intakes.values())
            if not owned and not _organizer(actor):
                raise PilotDenied("Application unavailable")
        record = {
            "id": self._new_id(),
            "organization_id": actor["organization_id"],
            "contact_email": email,
            "reason": reason,
            "created_at": self.now.isoformat(),
        }
        self.suppressions[(actor["organization_id"], email)] = record
        self._audit(actor, "suppression.recorded", record["id"])
        return {"reason": reason, "suppressed": True, "external_delivery": False}

    def save_schedule(self, actor: Mapping, campaign_id: str, payload: Mapping) -> dict:
        if not _organizer(actor):
            raise PilotDenied("Application unavailable")
        if not isinstance(payload, Mapping) or _protected(payload):
            raise PilotRejected("Unsupported field")
        role = self.roles.get(str(payload.get("role_id") or ""))
        if role is None or role["campaign_id"] != campaign_id or role["organization_id"] != actor["organization_id"]:
            raise PilotDenied("Application unavailable")
        timezone_name = payload.get("timezone")
        if not isinstance(timezone_name, str) or not _zone(timezone_name):
            raise PilotRejected("Invalid timezone")
        starts = _parse_time(payload.get("starts_at"))
        ends = _parse_time(payload.get("ends_at"))
        location = _clean_text(payload.get("location_label"), limit=120)
        if starts is None or ends is None or ends <= starts or location is None:
            raise PilotRejected("Invalid schedule")
        document = str(payload.get("document_url") or "")
        if document:
            link = validate_https_url(document)
            if not link.accepted:
                raise PilotRejected("Invalid video link")
            document = document.strip()
        record = {
            "id": self.schedules.get(role["id"], {}).get("id") or self._new_id(),
            "organization_id": actor["organization_id"],
            "campaign_id": campaign_id,
            "role_id": role["id"],
            "timezone": timezone_name.strip(),
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "location_label": location,
            "document_url": document,
            "updated_at": self.now.isoformat(),
            "published": False,
        }
        self.schedules[role["id"]] = record
        self._audit(actor, "schedule.saved", record["id"])
        return _schedule_view(record, include_document=_organizer(actor))

    def call_sheet(self, actor: Mapping, role_id: str) -> dict:
        schedule = self.schedules.get(role_id)
        if schedule is None or schedule["organization_id"] != actor.get("organization_id"):
            raise PilotDenied("Application unavailable")
        if actor.get("role") == "applicant":
            owns_role = any(
                row["role_id"] == role_id and row["applicant_id"] == actor.get("user_id")
                for row in self.intakes.values()
            )
            if not owns_role:
                raise PilotDenied("Application unavailable")
        elif not _reviewer(actor):
            raise PilotDenied("Application unavailable")
        local = _local_stamp(schedule["starts_at"], schedule["timezone"])
        people = []
        for row in self.intakes.values():
            if row["role_id"] != role_id or row["organization_id"] != schedule["organization_id"]:
                continue
            if row["consent_revoked_at"] or row["status"] != "SUBMITTED" or not row["shortlisted"]:
                continue
            if actor.get("role") == "applicant" and row["applicant_id"] != actor.get("user_id"):
                continue
            people.append({
                "receipt": row["receipt"],
                "display_name": "" if actor.get("role") == "reviewer" else row["display_name"],
                "contact_email": row["contact_email"] if actor.get("role") == "organizer" else "",
                "call_time": local,
                "role_title": self.roles[role_id]["title"],
            })
        people.sort(key=lambda item: item["receipt"])
        return {
            "role_id": role_id,
            "timezone": schedule["timezone"],
            "call_time": local,
            "location_label": schedule["location_label"],
            "invite_expired": _as_utc(datetime.fromisoformat(schedule["ends_at"])) <= self.now,
            "document_preview": "link" if schedule["document_url"] and _organizer(actor) else "hidden",
            "document_url": schedule["document_url"] if _organizer(actor) else "",
            "people": people,
            "external_delivery": False,
        }

    def export_csv(self, actor: Mapping, *, include_contact: bool = False) -> str:
        if not _organizer(actor):
            raise PilotDenied("Application unavailable")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        header = ["receipt", "role", "status", "stage", "shortlisted"]
        if include_contact:
            header.append("contact_email")
        writer.writerow(header)
        rows = [row for row in self.intakes.values() if row["organization_id"] == actor["organization_id"]]
        rows.sort(key=lambda item: item["receipt"])
        for row in rows:
            values = [
                row["receipt"],
                self.roles.get(row["role_id"], {}).get("title", ""),
                row["status"],
                row["stage"],
                "yes" if row["shortlisted"] else "no",
            ]
            if include_contact:
                values.append(row["contact_email"])
            writer.writerow(values)
        self._audit(actor, "export.requested", actor["organization_id"])
        text = buffer.getvalue()
        if "http://" in text or "https://" in text:
            raise PilotRejected("Request rejected")
        return text

    def list_audit(self, actor: Mapping, limit: int = 20, offset: int = 0) -> dict:
        if not _reviewer(actor):
            raise PilotDenied("Application unavailable")
        rows = [dict(item) for item in self.audit if item["organization_id"] == actor["organization_id"]]
        rows.sort(key=lambda item: (item["occurred_at"], item["id"]))
        return _page(rows, limit, offset)

    def issue_invite(self, actor: Mapping, campaign_id: str, payload: Mapping) -> dict:
        if not _organizer(actor):
            raise PilotDenied("Campaign unavailable")
        if not isinstance(payload, Mapping) or _protected(payload) or set(payload) - {"role_id", "expires_at"}:
            raise PilotRejected("Unsupported field")
        tenant = str(actor.get("tenant_id") or "")
        if not tenant:
            raise PilotDenied("Campaign unavailable")
        campaign = self.campaigns.get(campaign_id)
        if (
            campaign is None
            or campaign["organization_id"] != actor["organization_id"]
            or campaign.get("tenant_id") != tenant
        ):
            raise PilotDenied("Campaign unavailable")
        if campaign["status"] != "DRAFT" or campaign.get("published"):
            raise PilotRejected("Campaign cannot be published")
        role = self.roles.get(str(payload.get("role_id") or ""))
        if role is None or role["campaign_id"] != campaign_id or role["organization_id"] != actor["organization_id"]:
            raise PilotDenied("Campaign unavailable")
        expires = _parse_time(payload.get("expires_at"))
        if expires is None:
            raise PilotRejected("Invalid schedule")
        token = secrets.token_urlsafe(24)
        invite_id = self._new_id()
        status = "expired" if _as_utc(expires) <= self.now else "open"
        record = {
            "id": invite_id,
            "organization_id": actor["organization_id"],
            "tenant_id": tenant,
            "campaign_id": campaign_id,
            "role_id": role["id"],
            "token": token,
            "expires_at": _as_utc(expires).isoformat(),
            "status": status,
            "applicant_id": "",
            "application_id": "",
            "created_at": self.now.isoformat(),
            "redeemed_at": "",
            "published": False,
        }
        self.invites[invite_id] = record
        self._journey(actor, "invite.issued", invite_id)
        return _invite_view(record, include_token=True)

    def redeem_invite(self, actor: Mapping, token: str) -> dict:
        if actor.get("role") != "applicant" or actor.get("verified") is not True or not actor.get("user_id"):
            raise PilotDenied("Application unavailable")
        tenant = str(actor.get("tenant_id") or "")
        if not tenant or not actor.get("organization_id") or not isinstance(token, str) or not token.strip():
            raise PilotDenied("Application unavailable")
        found = next((row for row in self.invites.values() if row["token"] == token.strip()), None)
        if found is None or found["organization_id"] != actor["organization_id"] or found["tenant_id"] != tenant:
            raise PilotDenied("Application unavailable")
        if found["status"] == "revoked":
            raise PilotDenied("Application unavailable")
        campaign = self.campaigns.get(found["campaign_id"])
        if campaign is None or campaign["status"] != "DRAFT" or campaign.get("published"):
            raise PilotRejected("Campaign cannot be published")
        expires = _parse_time(found["expires_at"])
        if expires is None or _as_utc(expires) <= self.now or found["status"] == "expired":
            found["status"] = "expired"
            self._journey(actor, "invite.expired", found["id"])
            raise PilotRejected("Expired invite")
        if found["status"] == "redeemed":
            if found["applicant_id"] != actor["user_id"]:
                raise PilotDenied("Application unavailable")
            return _invite_view(found, include_token=False)
        if found["status"] != "open":
            raise PilotDenied("Application unavailable")
        found["status"] = "redeemed"
        found["applicant_id"] = actor["user_id"]
        found["application_id"] = self._new_id()
        found["redeemed_at"] = self.now.isoformat()
        self._journey(actor, "invite.redeemed", found["id"])
        return _invite_view(found, include_token=False)

    def dispatch_mock(self, actor: Mapping, message_id: str, *, fail: bool = False) -> dict:
        if not _organizer(actor):
            raise PilotDenied("Application unavailable")
        record = self.messages.get(message_id)
        if record is None or record["organization_id"] != actor["organization_id"]:
            raise PilotDenied("Application unavailable")
        if record["status"] not in {"approved", "failed_closed", "suppressed"}:
            raise PilotRejected("Request rejected")
        intake = self.intakes.get(record["application_id"]) if record["application_id"] else None
        override = _mock_override(self, record, intake)
        prior = ""
        for attempt in self.mock_attempts.values():
            if attempt["message_id"] == message_id and attempt["outcome"] == "mock_accepted" and attempt["mock_receipt"]:
                prior = attempt["mock_receipt"]
        attempt_number = 1 + sum(1 for item in self.mock_attempts.values() if item["message_id"] == message_id)
        result = _mock_transport(bool(fail)).dispatch(
            message_id=message_id,
            idempotency_key=record["idempotency_key"],
            channel=record["channel"],
            outcome_override=override,
            prior_receipt=prior,
            attempt=attempt_number,
        )
        record["attempt_count"] = int(record["attempt_count"]) + 1
        record["delivery_state"] = "not_sent"
        record["external_delivery"] = False
        record["delivered"] = False
        record["mock_outcome"] = result["outcome"]
        record["mock_receipt"] = result["mock_receipt"]
        if result["outcome"] in {"suppressed", "opted_out"}:
            record["status"] = "suppressed"
        elif result["outcome"] == "mock_failed":
            record["status"] = "failed_closed"
        attempt_id = self._new_id()
        self.mock_attempts[attempt_id] = {
            "id": attempt_id,
            "organization_id": actor["organization_id"],
            "message_id": message_id,
            "attempt_number": attempt_number,
            "outcome": result["outcome"],
            "mock_receipt": result["mock_receipt"],
            "failure_reason": result["mock_failure"],
            "provider": result["provider"],
            "created_at": self.now.isoformat(),
        }
        record["updated_at"] = self.now.isoformat()
        self._journey(actor, "mock.dispatched", attempt_id)
        view = _message_view(record)
        view["mock_failure"] = result["mock_failure"]
        view["real_delivery"] = False
        return view

    def record_mock_media(self, actor: Mapping, application_id: str, meta: Mapping) -> dict:
        row = self._own_intake(actor, application_id)
        if row["consent_revoked_at"] or row["status"] == "WITHDRAWN":
            raise PilotRejected("Consent revoked")
        status = meta.get("scan_status")
        if status not in {"CLEAN", "REJECTED"}:
            raise PilotRejected("Request rejected")
        reason = str(meta.get("scan_reason") or "")
        if len(reason) > 120:
            reason = reason[:120]
        media_id = self._new_id()
        record = {
            "id": media_id,
            "organization_id": actor["organization_id"],
            "application_id": application_id,
            "applicant_id": actor["user_id"],
            "mime_type": str(meta.get("mime_type") or ""),
            "byte_size": int(meta.get("byte_size") or 0),
            "scan_status": status,
            "scan_reason": reason,
            "public_url": "",
            "created_at": self.now.isoformat(),
        }
        self.mock_media[media_id] = record
        self._journey(actor, "upload.mock_recorded", media_id)
        return _mock_media_view(record)

    def list_mock_media(self, actor: Mapping, application_id: str) -> dict:
        row = self.intakes.get(application_id)
        if row is None or row["organization_id"] != actor.get("organization_id"):
            raise PilotDenied("Application unavailable")
        if actor.get("verified") is not True or actor.get("role") not in {"applicant", "reviewer", "organizer"}:
            raise PilotDenied("Application unavailable")
        if actor.get("role") == "applicant" and row["applicant_id"] != actor.get("user_id"):
            raise PilotDenied("Application unavailable")
        if actor.get("role") != "applicant" and not _reviewer(actor):
            raise PilotDenied("Application unavailable")
        items = [
            _mock_media_view(item)
            for item in self.mock_media.values()
            if item["organization_id"] == row["organization_id"] and item["application_id"] == application_id
        ]
        items.sort(key=lambda item: item["id"])
        return {
            "items": items,
            "media_uploads_enabled": False,
            "bytes_released": False,
            "public_url": "",
        }

    def snapshot(self, actor: Mapping, campaign_id: str = "") -> dict:
        """Read the saved sandbox copy. This does not create a row or send a message."""
        if actor.get("verified") is not True or not actor.get("user_id") or not actor.get("organization_id"):
            raise PilotDenied("Application unavailable")
        role_name = actor.get("role")
        if role_name not in {"organizer", "reviewer", "applicant"}:
            raise PilotDenied("Application unavailable")
        organization_id = actor["organization_id"]
        selected = str(campaign_id or "")
        roles = [
            _role_view(row) for row in self.roles.values()
            if row["organization_id"] == organization_id and (not selected or row["campaign_id"] == selected)
        ]
        roles.sort(key=lambda item: (item["created_at"], item["id"]))
        intakes = []
        for row in self.intakes.values():
            if row["organization_id"] != organization_id:
                continue
            if selected and row["campaign_id"] != selected:
                continue
            if role_name == "applicant" and row["applicant_id"] != actor["user_id"]:
                continue
            if role_name == "organizer":
                view = _organizer_view(row)
            elif role_name == "reviewer":
                view = _reviewer_view(row)
            else:
                view = _applicant_view(row)
            intakes.append(view)
        intakes.sort(key=lambda item: (item["created_at"], item["id"]))
        messages = []
        if role_name == "organizer":
            for row in self.messages.values():
                if row["organization_id"] != organization_id:
                    continue
                application_id = str(row.get("application_id") or "")
                if selected and application_id:
                    intake = self.intakes.get(application_id)
                    if (
                        intake is None
                        or intake.get("organization_id") != organization_id
                        or intake.get("campaign_id") != selected
                    ):
                        continue
                view = _message_view(row)
                view["application_id"] = application_id
                messages.append(view)
            messages.sort(key=lambda item: item["id"])
        invites = []
        for row in self.invites.values():
            if row["organization_id"] != organization_id:
                continue
            if selected and row["campaign_id"] != selected:
                continue
            if role_name == "organizer":
                invites.append(_invite_view(row, include_token=True))
            elif role_name == "applicant" and row["applicant_id"] == actor["user_id"]:
                invites.append(_invite_view(row, include_token=False))
        invites.sort(key=lambda item: item["id"])
        return {
            "label": "Demo / Early Access",
            "published": False,
            "delivered": False,
            "external_delivery": False,
            "media_uploads_enabled": False,
            "roles": roles[:PAGE_LIMIT],
            "intakes": intakes[:PAGE_LIMIT],
            "messages": messages[:PAGE_LIMIT],
            "invites": invites[:PAGE_LIMIT],
        }

    def seed_harborlight(self, actor: Mapping, campaign_id: str) -> dict:
        if not _organizer(actor):
            raise PilotDenied("Campaign unavailable")
        plan = sample_harborlight_plan()
        created = []
        for role in plan["roles"]:
            title = str(role["title"]).strip().lower()
            existing = next(
                (
                    row for row in self.roles.values()
                    if row["organization_id"] == actor["organization_id"]
                    and row["campaign_id"] == campaign_id
                    and row["title"].strip().lower() == title
                ),
                None,
            )
            if existing is None:
                created.append(self.create_role(actor, campaign_id, role))
            else:
                created.append(_role_view(existing))
        first = created[0]
        schedule = self.save_schedule(actor, campaign_id, {
            "role_id": first["id"],
            "timezone": "America/New_York",
            "starts_at": "2026-11-18T15:00:00+00:00",
            "ends_at": "2026-11-18T18:00:00+00:00",
            "location_label": "Fictional reading room",
            "document_url": "https://example.invalid/harborlight-side.pdf",
        })
        message = self.draft_message(actor, {
            "kind": "confirmation",
            "idempotency_key": "harborlight-preview",
            "channel": "email",
            "application_id": "",
        })
        return {
            "label": plan["label"],
            "title": plan["title"],
            "published": False,
            "roles": created,
            "schedule": schedule,
            "message": message,
            "offer": plan["offer"],
        }

    def _own_intake(self, actor: Mapping, application_id: str) -> dict:
        row = self.intakes.get(application_id)
        if row is None or actor.get("role") != "applicant" or row["applicant_id"] != actor.get("user_id"):
            raise PilotDenied("Application unavailable")
        if row["organization_id"] != actor.get("organization_id"):
            raise PilotDenied("Application unavailable")
        return row

    def _messages_today(self, organization_id: str) -> int:
        day = self.now.date().isoformat()
        return sum(
            1 for item in self.messages.values()
            if item["organization_id"] == organization_id and item["created_at"][:10] == day
        )


def _build_intake(*, actor, application_id, campaign_id, role, payload, now, existing) -> dict | None:
    if payload.get("consent_accepted") is not True:
        return None
    version = payload.get("consent_version")
    if not isinstance(version, str) or not version.strip() or len(version) > 32 or any(char in "<>" for char in version):
        return None
    age = payload.get("age_years")
    if isinstance(age, bool) or not isinstance(age, int) or age < role["minimum_age"] or age < MINIMUM_AGE:
        return None
    name = payload.get("display_name")
    if not isinstance(name, str) or _NAME.fullmatch(name.strip()) is None:
        return None
    email = normalize_email(payload.get("contact_email"))
    if email is None:
        return None
    link = validate_https_url(payload.get("video_url"))
    if not link.accepted:
        return None
    retention = payload.get("retention_days", DEFAULT_RETENTION_DAYS)
    if isinstance(retention, bool) or not isinstance(retention, int) or not 1 <= retention <= MAX_RETENTION_DAYS:
        return None
    answers = payload.get("answers", {})
    if not isinstance(answers, Mapping) or _protected(answers):
        return None
    expected = {item["id"] for item in role["questions"]}
    if set(answers) - expected:
        return None
    cleaned_answers = {}
    for key, value in answers.items():
        text = _clean_text(value, limit=500)
        if text is None:
            return None
        cleaned_answers[key] = text
    created = existing["created_at"] if existing else now.isoformat()
    return {
        "id": application_id,
        "organization_id": actor["organization_id"],
        "campaign_id": campaign_id,
        "role_id": role["id"],
        "applicant_id": actor["user_id"],
        "display_name": name.strip(),
        "contact_email": email,
        "video_url": str(payload["video_url"]).strip(),
        "answers": cleaned_answers,
        "age_years": age,
        "consent_version": version.strip(),
        "retention_notice": RETENTION_NOTICE,
        "retention_days": retention,
        "consent_expires_at": (now + timedelta(days=retention)).isoformat(),
        "consent_revoked_at": "",
        "receipt": receipt_code(application_id),
        "status": "DRAFT",
        "stage": "New",
        "shortlisted": False,
        "minimized": False,
        "created_at": created,
        "updated_at": now.isoformat(),
        "published": False,
    }


def _intake_error(role: Mapping, payload: Mapping) -> str:
    if payload.get("consent_accepted") is not True:
        return "Consent required"
    version = payload.get("consent_version")
    if not isinstance(version, str) or not version.strip():
        return "Consent version required"
    age = payload.get("age_years")
    if isinstance(age, bool) or not isinstance(age, int) or age < MINIMUM_AGE or age < role["minimum_age"]:
        return "Applicant does not meet the minimum age"
    if normalize_email(payload.get("contact_email")) is None:
        return "Invalid email"
    if not isinstance(payload.get("display_name"), str) or _NAME.fullmatch(str(payload.get("display_name")).strip()) is None:
        return "Invalid name"
    if not validate_https_url(payload.get("video_url")).accepted:
        return "Invalid video link"
    return "Request rejected"


def _submit_block(row: Mapping, role: Mapping, now: datetime) -> str:
    if row["consent_revoked_at"]:
        return "Consent revoked"
    expires = _parse_time(row["consent_expires_at"])
    if expires is None or expires <= now:
        return "Consent expired"
    deadline = _parse_time(role["deadline"])
    if deadline is None or deadline <= now:
        return "Deadline passed"
    expected = {item["id"] for item in role["questions"]}
    if set(row["answers"]) != expected:
        return "Eligibility required"
    if not row["video_url"]:
        return "Invalid video link"
    return ""


def _clear_contact(row: dict) -> None:
    row["display_name"] = ""
    row["contact_email"] = ""
    row["video_url"] = ""
    row["answers"] = {}
    row["minimized"] = True


def _channel_status(*, channel, suppressed, sms_configured, whatsapp_configured) -> tuple[str, str]:
    if channel == "sms" and not sms_configured:
        return "SMS is not configured", "failed_closed"
    if channel == "whatsapp" and not whatsapp_configured:
        return "WhatsApp is not configured", "failed_closed"
    if channel not in {"email", "sms", "whatsapp"}:
        return "Request rejected", "failed_closed"
    if suppressed:
        return "Suppressed", "suppressed"
    if channel in {"sms", "whatsapp"}:
        return "Outbound disabled", "failed_closed"
    return "Outbound disabled", "draft"


def _render_message(kind: str, *, receipt: str, role_title: str, when: str) -> str:
    if kind == "confirmation":
        return f"Sandbox receipt {receipt or 'pending'}. Your application was recorded. This message was not sent."
    if kind == "invite":
        return f"Sandbox callback draft for {role_title or 'the role'}. No invitation was delivered."
    if kind == "reminder":
        return f"Sandbox reminder for {when or 'a later call'}. No reminder was delivered."
    return "Sandbox schedule update. No update was delivered."


def _invite_expired(directory: PilotDirectory, intake: Mapping | None) -> bool:
    if intake is None:
        return False
    schedule = directory.schedules.get(intake["role_id"])
    if schedule is None:
        return False
    ends = _parse_time(schedule["ends_at"])
    return ends is not None and ends <= directory.now


def _zone(name: str) -> bool:
    try:
        ZoneInfo(name.strip())
    except ZoneInfoNotFoundError:
        return False
    return True


def _local_stamp(starts_at: str, timezone_name: str) -> str:
    parsed = _parse_time(starts_at)
    if parsed is None:
        return ""
    return parsed.astimezone(ZoneInfo(timezone_name)).isoformat()


def _bounds(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or isinstance(offset, bool) or not isinstance(limit, int) or not isinstance(offset, int):
        raise PilotRejected("Request rejected")
    if limit < 1 or limit > PAGE_LIMIT or offset < 0 or offset > 10000:
        raise PilotRejected("Request rejected")
    return limit, offset


def _page(items: list, limit: int, offset: int) -> dict:
    limit, offset = _bounds(limit, offset)
    return {"items": items[offset:offset + limit], "limit": limit, "offset": offset}


def _search_blob(row: Mapping, roles: Mapping) -> str:
    title = roles.get(row["role_id"], {}).get("title", "")
    return " ".join((row["receipt"], title, row["display_name"], row["status"]))


def _role_view(record: Mapping) -> dict:
    return {
        "id": record["id"],
        "campaign_id": record["campaign_id"],
        "title": record["title"],
        "requirements": record["requirements"],
        "deadline": record["deadline"],
        "minimum_age": record["minimum_age"],
        "questions": list(record["questions"]),
        "created_at": record["created_at"],
        "published": False,
    }


def _applicant_view(record: Mapping) -> dict:
    return {
        "id": record["id"],
        "campaign_id": record["campaign_id"],
        "role_id": record["role_id"],
        "status": record["status"],
        "receipt": record["receipt"],
        "display_name": record["display_name"],
        "contact_email": record["contact_email"],
        "video_url": record["video_url"],
        "consent_expires_at": record["consent_expires_at"],
        "consent_revoked": bool(record["consent_revoked_at"]),
        "retention_notice": RETENTION_NOTICE,
        "created_at": record["created_at"],
        "published": False,
    }


def _organizer_view(record: Mapping) -> dict:
    view = _applicant_view(record)
    view["stage"] = record["stage"]
    view["shortlisted"] = record["shortlisted"]
    view["video_on_file"] = bool(record["video_url"])
    return view


def _reviewer_view(record: Mapping) -> dict:
    return {
        "id": record["id"],
        "campaign_id": record["campaign_id"],
        "role_id": record["role_id"],
        "status": record["status"],
        "receipt": record["receipt"],
        "stage": record["stage"],
        "shortlisted": record["shortlisted"],
        "video_on_file": bool(record["video_url"]),
        "video_url": "",
        "contact_email": "",
        "display_name": "",
        "consent_revoked": bool(record["consent_revoked_at"]),
        "created_at": record["created_at"],
        "published": False,
    }


def _message_view(record: Mapping) -> dict:
    return {
        "id": record["id"],
        "kind": record["kind"],
        "channel": record["channel"],
        "status": record["status"],
        "body": record["body"],
        "attempt_count": record["attempt_count"],
        "approved_by": record["approved_by"],
        "delivery_state": "not_sent",
        "external_delivery": False,
        "delivered": False,
        "real_delivery": False,
        "idempotency_key": record["idempotency_key"],
        "mock_outcome": record.get("mock_outcome") or "not_attempted",
        "mock_receipt": record.get("mock_receipt") or "",
        "mock_provider": "disposable-mock" if record.get("mock_outcome") else "",
    }


def _invite_view(record: Mapping, *, include_token: bool) -> dict:
    return {
        "id": record["id"],
        "campaign_id": record["campaign_id"],
        "role_id": record["role_id"],
        "expires_at": record["expires_at"],
        "status": record["status"],
        "application_id": record["application_id"],
        "token": record["token"] if include_token else "",
        "published": False,
        "public_url": "",
        "external_delivery": False,
    }


def _mock_media_view(record: Mapping) -> dict:
    return {
        "id": record["id"],
        "application_id": record["application_id"],
        "mime_type": record["mime_type"],
        "byte_size": record["byte_size"],
        "scan_status": record["scan_status"],
        "scan_reason": record["scan_reason"],
        "public_url": "",
        "playback": "unavailable",
        "bytes_released": False,
        "media_uploads_enabled": False,
    }


def _mock_transport(fail: bool):
    try:
        from .casting_mock_transport import MockTransport
    except ImportError:
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parent / "casting_mock_transport.py"
        spec = importlib.util.spec_from_file_location("casting_mock_transport_standalone", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        MockTransport = module.MockTransport
    return MockTransport(fail=fail)


def _mock_override(directory: PilotDirectory, record: Mapping, intake: Mapping | None) -> str | None:
    if intake is not None:
        suppression = directory.suppressions.get((intake["organization_id"], intake.get("contact_email")))
        if suppression is not None:
            return "opted_out" if suppression.get("reason") == "unsubscribe" else "suppressed"
        if intake.get("consent_revoked_at") or intake.get("contact_email") == "":
            return "suppressed"
    if record.get("status") == "suppressed":
        return "suppressed"
    return None


def _schedule_view(record: Mapping, *, include_document: bool) -> dict:
    return {
        "id": record["id"],
        "role_id": record["role_id"],
        "timezone": record["timezone"],
        "starts_at": record["starts_at"],
        "ends_at": record["ends_at"],
        "location_label": record["location_label"],
        "document_url": record["document_url"] if include_document else "",
        "published": False,
        "external_delivery": False,
    }


def run_harborlight_walkthrough(now: datetime | None = None) -> dict:
    """One fictional month. Synthetic adults only. No message leaves the sandbox."""
    clock = now or datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
    book = PilotDirectory(clock, id_factory=_sequence())
    organizer = {"user_id": "organizer-sample", "organization_id": "org-harbor", "role": "organizer", "verified": True}
    seeded = book.seed_harborlight(organizer, "campaign-harbor")
    lead = seeded["roles"][0]
    minor = _person("minor-sample", "org-harbor")
    duplicate = _person("jordan-sample", "org-harbor")
    priya = _person("priya-sample", "org-harbor")
    ellis = _person("ellis-sample", "org-other")
    outcomes = []
    try:
        book.save_intake(minor, application_id="app-minor", campaign_id="campaign-harbor", payload=_tape(
            lead["id"], "Minor Example", "minor@example.invalid", age=17,
        ))
        outcomes.append("minor-accepted")
    except PilotRejected as exc:
        outcomes.append(exc.args[0])
    first = book.save_intake(duplicate, application_id="app-jordan", campaign_id="campaign-harbor", payload=_tape(
        lead["id"], "Jordan Hale", "jordan.hale@example.invalid",
    ))
    resumed = book.save_intake(duplicate, application_id="app-jordan", campaign_id="campaign-harbor", payload=_tape(
        lead["id"], "Jordan Hale", "jordan.hale@example.invalid", answer="Yes",
    ))
    try:
        book.save_intake(_person("other-sample", "org-harbor"), application_id="app-copy", campaign_id="campaign-harbor", payload=_tape(
            lead["id"], "Other Person", "jordan.hale@example.invalid",
        ))
        outcomes.append("duplicate-accepted")
    except PilotRejected as exc:
        outcomes.append(exc.args[0])
    book.now = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
    submitted = book.submit_intake(duplicate, "app-jordan")
    priya_row = book.save_intake(priya, application_id="app-priya", campaign_id="campaign-harbor", payload=_tape(
        lead["id"], "Priya Shah", "priya.shah@example.invalid", answer="Yes",
    ))
    book.submit_intake(priya, "app-priya")
    try:
        book.save_intake(ellis, application_id="app-ellis", campaign_id="campaign-harbor", payload=_tape(
            lead["id"], "Ellis Ward", "ellis.ward@example.invalid",
        ))
        outcomes.append("cross-tenant-accepted")
    except PilotDenied:
        outcomes.append("cross-tenant-denied")
    reviewer = {"user_id": "reviewer-sample", "organization_id": "org-harbor", "role": "reviewer", "verified": True}
    book.set_review(reviewer, "app-jordan", stage="In review", shortlisted=True)
    rubric = book.add_rubric(reviewer, "app-jordan", {"criterion": "clarity", "score": 4, "comment": "Clear sample read."})
    queue = book.queue(reviewer, query="Jordan", shortlisted="true")
    book.now = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
    draft = book.draft_message(organizer, {
        "kind": "invite", "application_id": "app-jordan", "idempotency_key": "invite-jordan-01", "channel": "email",
    })
    approved = book.approve_message(organizer, draft["id"])
    retried = book.retry_message(organizer, draft["id"])
    try:
        book.draft_message(organizer, {
            "kind": "reminder", "application_id": "app-jordan", "idempotency_key": "sms-jordan-01", "channel": "sms",
        })
        outcomes.append("sms-drafted")
    except PilotRejected as exc:
        outcomes.append(exc.args[0])
    sheet = book.call_sheet(organizer, lead["id"])
    book.revoke_intake(priya, "app-priya")
    suppressed = book.draft_message(organizer, {
        "kind": "reminder", "application_id": "app-priya", "idempotency_key": "remind-priya-01", "channel": "email",
    })
    book.now = datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)
    exported = book.export_csv(organizer, include_contact=False)
    return {
        "label": "Demo / Early Access",
        "receipt": first["receipt"],
        "resumed_receipt": resumed["receipt"],
        "submitted_status": submitted["status"],
        "priya_receipt": priya_row["receipt"],
        "outcomes": outcomes,
        "rubric_decision": rubric["decision"],
        "automatic_cast": rubric["automatic_cast"],
        "reviewer_hides_contact": queue["items"][0]["contact_email"] == "" if queue["items"] else False,
        "reviewer_hides_link": queue["items"][0]["video_url"] == "" if queue["items"] else False,
        "approved_status": approved["status"],
        "delivered": approved["delivered"] or retried["delivered"],
        "external_delivery": approved["external_delivery"] or retried["external_delivery"],
        "retry_attempts": retried["attempt_count"],
        "call_sheet_count": len(sheet["people"]),
        "suppressed_status": suppressed["status"],
        "export_has_link": "https://" in exported,
        "export_has_jordan": "CA-" in exported,
        "audit_actions": [item["action"] for item in book.audit],
        "published": False,
    }


def _sequence():
    counter = {"n": 0}

    def _next() -> str:
        counter["n"] += 1
        return f"id{counter['n']:04d}"

    return _next


def _person(user_id: str, organization_id: str) -> dict:
    return {"user_id": user_id, "organization_id": organization_id, "role": "applicant", "verified": True}


def _tape(role_id: str, name: str, email: str, *, age: int = 28, answer: str = "") -> dict:
    payload = {
        "role_id": role_id,
        "display_name": name,
        "contact_email": email,
        "video_url": "https://example.invalid/tapes/sample",
        "age_years": age,
        "consent_accepted": True,
        "consent_version": "sandbox-v1",
        "retention_days": 30,
        "answers": {},
    }
    if answer:
        payload["answers"] = {"union": answer}
    return payload
