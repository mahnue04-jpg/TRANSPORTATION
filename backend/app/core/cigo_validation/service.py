"""Assessment intake records stored in SQLite. This module does not send mail or HTTP."""
from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

CURRENCIES = ("USD", "EUR", "GBP", "CAD")
FOLLOW_UP = ("none", "email")
IDEA_MIN = 12
IDEA_MAX = 500
BUDGET_MAX = Decimal("1000000000")
APPROVED_VIDEO_URL = "https://v3b.fal.media/files/b/0aae5147/n7o5OtUWOjW2VvYEWJr9f_output.mp4"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SPACE = re.compile(r"\s+")

FICTIONAL = (
    {
        "id": "cigo_fictional_bakery",
        "idea": "A neighborhood bakery wants a weekly specials note drafted for the owner to approve.",
        "budget": "250.00",
        "currency": "USD",
        "email": "",
        "follow_up": "none",
        "consent": True,
    },
    {
        "id": "cigo_fictional_tutor",
        "idea": "A tutor wants parent reminder drafts prepared, with the tutor approving each send.",
        "budget": "75.00",
        "currency": "GBP",
        "email": "tutor@example.com",
        "follow_up": "email",
        "consent": True,
    },
    {
        "id": "cigo_fictional_clinic",
        "idea": "A small clinic wants intake questions turned into a checklist the owner reviews.",
        "budget": "500.00",
        "currency": "CAD",
        "email": "desk@example.com",
        "follow_up": "email",
        "consent": True,
    },
)


def demo_enabled() -> bool:
    """Local mock only. Production never mounts this, even if the flag is set."""
    runtime = os.getenv("RUNTIME_ENVIRONMENT", os.getenv("ENVIRONMENT", "development")).strip().lower()
    if runtime in {"production", "prod"}:
        return False
    return os.getenv("CIGO_VALIDATION_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}


def default_db_path() -> Path:
    configured = os.getenv("CIGO_VALIDATION_DB", "").strip()
    if configured:
        return Path(configured)
    if os.path.isdir("/data/onboarding_docs"):
        return Path("/data/onboarding_docs/cigo_validation.sqlite")
    return Path(__file__).resolve().parents[3] / "data" / "cigo-validation.sqlite"


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
        errors["consent"] = "Consent is required before a record can be saved."
    return errors


class CigoValidationDemo:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self._lock = threading.Lock()
        self._init()

    def bind(self, path: Path) -> None:
        self.path = Path(path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    idea TEXT NOT NULL,
                    idea_key TEXT NOT NULL,
                    budget TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    email TEXT NOT NULL,
                    email_key TEXT NOT NULL,
                    consent INTEGER NOT NULL,
                    follow_up TEXT NOT NULL,
                    follow_up_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS records_dedupe ON records(idea_key, email_key);
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    at TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    destination TEXT,
                    sent INTEGER NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS failures (
                    id TEXT PRIMARY KEY,
                    at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    fields_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO meta(key, value) VALUES ('outbound_sends', '0')
                    ON CONFLICT(key) DO NOTHING;
                """
            )

    @property
    def outbound_sends(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'outbound_sends'").fetchone()
        return int(row["value"]) if row else 0

    def reset(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM records")
            conn.execute("DELETE FROM alerts")
            conn.execute("DELETE FROM failures")
            conn.execute("UPDATE meta SET value = '0' WHERE key = 'outbound_sends'")

    def seed_fictional(self) -> dict:
        created = 0
        for item in FICTIONAL:
            result = self.submit(item, record_id=item["id"], source="fictional")
            if result.get("created"):
                created += 1
        return {"ok": True, "status": "seeded", "created": created, "http_status": 200}

    def submit(self, payload: object, *, force_failure: str | None = None, record_id: str | None = None, source: str = "visitor") -> dict:
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
        follow = str(data["follow_up"])
        follow_status = "prepared_not_sent" if follow == "email" else "not_requested"
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM records WHERE idea_key = ? AND email_key = ?",
                (idea_key, email_key),
            ).fetchone()
            if existing:
                alert = self._insert_alert(
                    conn,
                    existing["id"],
                    "duplicate_review",
                    None,
                    "Duplicate idea and email. The original id was kept. No email was sent.",
                )
                record = self._public(existing)
                status = "duplicate"
                created = False
                http_status = 200
            else:
                record_row = {
                    "id": record_id or _new_id("cigo"),
                    "created_at": _now(),
                    "idea": idea,
                    "idea_key": idea_key,
                    "budget": data["_budget"],
                    "currency": data["_currency"],
                    "email": email,
                    "email_key": email_key,
                    "consent": 1,
                    "follow_up": follow,
                    "follow_up_status": follow_status,
                    "status": "recorded",
                    "source": source,
                }
                conn.execute(
                    """
                    INSERT INTO records (
                        id, created_at, idea, idea_key, budget, currency, email, email_key,
                        consent, follow_up, follow_up_status, status, source
                    ) VALUES (
                        :id, :created_at, :idea, :idea_key, :budget, :currency, :email, :email_key,
                        :consent, :follow_up, :follow_up_status, :status, :source
                    )
                    """,
                    record_row,
                )
                destination = email if follow == "email" else None
                body = (
                    f"Follow-up prepared for {email}. It was not delivered."
                    if destination
                    else "Owner review recorded. No follow-up was requested, and no email was sent."
                )
                alert = self._insert_alert(conn, record_row["id"], "owner_review" if not destination else "follow_up_prepared", destination, body)
                record = self._public(conn.execute("SELECT * FROM records WHERE id = ?", (record_row["id"],)).fetchone())
                status = "created"
                created = True
                http_status = 201
        return {
            "ok": True,
            "status": status,
            "http_status": http_status,
            "created": created,
            "record": record,
            "alert": alert,
            "outbound_sends": self.outbound_sends,
        }

    def snapshot(self) -> dict:
        with self._lock, self._connect() as conn:
            records = [self._public(row) for row in conn.execute("SELECT * FROM records ORDER BY rowid")]
            alerts = [self._alert_public(row) for row in conn.execute("SELECT * FROM alerts ORDER BY rowid")]
            failures = [self._failure_public(row) for row in conn.execute("SELECT * FROM failures ORDER BY rowid")]
            outbound = conn.execute("SELECT value FROM meta WHERE key = 'outbound_sends'").fetchone()
        return {
            "records": records,
            "alerts": alerts,
            "failures": failures,
            "outbound_sends": int(outbound["value"]) if outbound else 0,
            "database": self.path.name,
            "live_email_delivery": False,
        }

    def workflow(self) -> dict:
        snap = self.snapshot()
        return {
            "name": "CIGO product-validation intake",
            "live_email_delivery": False,
            "outbound_sends": snap["outbound_sends"],
            "approved_video_url": APPROVED_VIDEO_URL,
            "steps": [
                "Visitor opens the campaign page and watches the approved vertical presenter.",
                "Visitor submits idea, budget, currency, optional email, follow-up choice, and consent.",
                "Invalid fields are rejected and stored as a failure. No record is created.",
                "A repeated idea and email returns the original id.",
                "A new idea is stored in SQLite with a unique cigo_ id.",
                "If follow-up is email, a notification is prepared and marked not sent.",
                "Records, alerts, and failures can be exported as JSON or CSV.",
            ],
            "records": snap["records"],
            "alerts": snap["alerts"],
        }

    def export_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "id", "created_at", "idea", "budget", "currency", "email", "consent",
                "follow_up", "follow_up_status", "status", "source",
            ],
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
        import json
        item = {"id": _new_id("fail"), "at": _now(), "kind": kind, "fields": fields}
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO failures (id, at, kind, fields_json) VALUES (?, ?, ?, ?)",
                (item["id"], item["at"], kind, json.dumps(fields)),
            )
        return item

    def _insert_alert(self, conn: sqlite3.Connection, record_id: str, kind: str, destination: str | None, body: str) -> dict:
        item = {
            "id": _new_id("alert"),
            "at": _now(),
            "record_id": record_id,
            "kind": kind,
            "status": "suppressed_no_outbound",
            "destination": destination,
            "sent": 0,
            "body": body,
        }
        conn.execute(
            """
            INSERT INTO alerts (id, at, record_id, kind, status, destination, sent, body)
            VALUES (:id, :at, :record_id, :kind, :status, :destination, :sent, :body)
            """,
            item,
        )
        item["sent"] = False
        return item

    @staticmethod
    def _public(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "idea": row["idea"],
            "budget": row["budget"],
            "currency": row["currency"],
            "email": row["email"],
            "consent": bool(row["consent"]),
            "follow_up": row["follow_up"],
            "follow_up_status": row["follow_up_status"],
            "status": row["status"],
            "source": row["source"],
        }

    @staticmethod
    def _alert_public(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "at": row["at"],
            "record_id": row["record_id"],
            "kind": row["kind"],
            "status": row["status"],
            "destination": row["destination"],
            "sent": bool(row["sent"]),
            "body": row["body"],
        }

    @staticmethod
    def _failure_public(row: sqlite3.Row) -> dict:
        import json
        return {
            "id": row["id"],
            "at": row["at"],
            "kind": row["kind"],
            "fields": json.loads(row["fields_json"]),
        }
