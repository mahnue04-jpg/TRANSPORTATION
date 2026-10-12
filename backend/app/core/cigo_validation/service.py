"""Mock product-validation records. Nothing in this module sends mail or HTTP."""
from __future__ import annotations

import csv
import io
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

CURRENCIES = ("USD", "EUR", "GBP", "CAD")
FOLLOW_UP = ("none", "email")
IDEA_MIN = 12
IDEA_MAX = 500
BUDGET_MAX = Decimal("1000000000")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SPACE = re.compile(r"\s+")


def demo_enabled() -> bool:
    """Local mock only. Production never mounts this, even if the flag is set."""
    runtime = os.getenv("RUNTIME_ENVIRONMENT", os.getenv("ENVIRONMENT", "development")).strip().lower()
    if runtime in {"production", "prod"}:
        return False
    return os.getenv("CIGO_VALIDATION_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _idea_key(idea: str) -> str:
    return _SPACE.sub(" ", idea.strip().lower())


def _email_key(email: str) -> str:
    return email.strip().lower()


def _parse_budget(value: object) -> tuple[Decimal | None, str | None]:
    if isinstance(value, bool) or value is None or isinstance(value, (list, dict)):
        return None, "Enter a budget amount as a number."
    text = str(value).strip()
    if not text or any(ch.isalpha() or ch in "$,€£" for ch in text):
        return None, "Enter a budget amount as a number. Choose the currency separately."
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None, "Enter a budget amount as a number."
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return None, "Use at most two decimal places."
    if amount <= 0:
        return None, "Budget must be greater than zero."
    if amount > BUDGET_MAX:
        return None, "Budget is too large for this mock demo."
    return amount, None


def validate(payload: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    idea = payload.get("idea")
    if not isinstance(idea, str) or len(_idea_key(idea)) < IDEA_MIN:
        errors["idea"] = f"Describe the idea in at least {IDEA_MIN} characters."
    elif len(idea.strip()) > IDEA_MAX:
        errors["idea"] = f"Keep the idea to {IDEA_MAX} characters."

    amount, budget_error = _parse_budget(payload.get("budget"))
    if budget_error:
        errors["budget"] = budget_error
    else:
        payload["_budget"] = f"{amount:.2f}"

    currency = payload.get("currency")
    if not isinstance(currency, str) or currency.strip().upper() not in CURRENCIES:
        errors["currency"] = "Choose USD, EUR, GBP, or CAD."
    else:
        payload["_currency"] = currency.strip().upper()

    email = payload.get("email", "")
    if email is None:
        email = ""
    if not isinstance(email, str):
        errors["email"] = "Email must be text, or leave it blank."
        email = ""
    email = email.strip()
    if email and not _EMAIL.match(email):
        errors["email"] = "Enter a valid email or leave it blank."

    follow = payload.get("follow_up")
    if follow not in FOLLOW_UP:
        errors["follow_up"] = "Choose no follow-up, or follow-up by email."
    elif follow == "email" and not email:
        errors["email"] = "Email is required when follow-up is requested."
        errors["follow_up"] = "Add an email, or choose no follow-up."

    if payload.get("consent") is not True:
        errors["consent"] = "Consent is required before a mock record can be saved."
    return errors


class CigoValidationDemo:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self.alerts: list[dict] = []
        self.failures: list[dict] = []
        self.outbound_sends = 0
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self.records.clear()
            self.alerts.clear()
            self.failures.clear()
            self.outbound_sends = 0

    def submit(self, payload: object, *, force_failure: str | None = None) -> dict:
        if not isinstance(payload, dict):
            failure = self._failure("invalid_input", {"body": "Request body must be a JSON object."})
            return self._invalid(failure)
        data = dict(payload)
        errors = validate(data)
        if errors:
            return self._invalid(self._failure("invalid_input", errors))
        if (force_failure or "").strip().lower() == "store":
            failure = self._failure("store_unavailable", {"store": "Simulated storage failure. Nothing was saved."})
            return {"ok": False, "status": "failed", "http_status": 503, "failure": failure, "outbound_sends": self.outbound_sends}

        idea = str(data.get("idea") or "").strip()
        email = str(data.get("email") or "").strip()
        idea_key = _idea_key(idea)
        email_key = _email_key(email)
        with self._lock:
            existing = next(
                (row for row in self.records if row["idea_key"] == idea_key and row["email_key"] == email_key),
                None,
            )
            if existing:
                alert = self._alert(existing["id"], "duplicate_review")
                return {
                    "ok": True,
                    "status": "duplicate",
                    "http_status": 200,
                    "created": False,
                    "record": self._public(existing),
                    "alert": alert,
                    "outbound_sends": self.outbound_sends,
                }
            record = {
                "id": _new_id("cigo"),
                "created_at": _now(),
                "idea": idea,
                "idea_key": idea_key,
                "budget": data["_budget"],
                "currency": data["_currency"],
                "email": email,
                "email_key": email_key,
                "consent": True,
                "follow_up": data["follow_up"],
                "status": "recorded",
            }
            self.records.append(record)
            alert = self._alert(record["id"], "owner_review")
        return {
            "ok": True,
            "status": "created",
            "http_status": 201,
            "created": True,
            "record": self._public(record),
            "alert": alert,
            "outbound_sends": self.outbound_sends,
        }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "records": [self._public(row) for row in self.records],
                "alerts": list(self.alerts),
                "failures": list(self.failures),
                "outbound_sends": self.outbound_sends,
            }

    def export_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=["id", "created_at", "idea", "budget", "currency", "email", "consent", "follow_up", "status"],
        )
        writer.writeheader()
        for row in self.snapshot()["records"]:
            writer.writerow(row)
        return buffer.getvalue()

    def _invalid(self, failure: dict) -> dict:
        return {
            "ok": False,
            "status": "invalid",
            "http_status": 422,
            "failure": failure,
            "outbound_sends": self.outbound_sends,
        }

    def _failure(self, kind: str, fields: dict[str, str]) -> dict:
        item = {"id": _new_id("fail"), "at": _now(), "kind": kind, "fields": fields}
        with self._lock:
            self.failures.append(item)
        return item

    def _alert(self, record_id: str, kind: str) -> dict:
        item = {
            "id": _new_id("alert"),
            "at": _now(),
            "record_id": record_id,
            "kind": kind,
            "status": "suppressed_no_outbound",
            "destination": None,
            "sent": False,
        }
        self.alerts.append(item)
        return item

    @staticmethod
    def _public(row: dict) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "idea": row["idea"],
            "budget": row["budget"],
            "currency": row["currency"],
            "email": row["email"],
            "consent": row["consent"],
            "follow_up": row["follow_up"],
            "status": row["status"],
        }
