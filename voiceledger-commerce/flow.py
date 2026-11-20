"""Isolated VoiceLedger Pro TEST-only checkout and fulfillment.

Not imported by the AMICOR production app. No live Stripe keys, charging, or emails.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

SKU = "voiceledger_pro"
PRICE_CENTS = 3900  # proposed one-time USD price, not approval to sell
EVENTS = frozenset({"checkout.session.completed", "checkout.session.async_payment_succeeded"})


class CheckoutError(RuntimeError):
    pass


def email_normalized(value: str) -> str:
    value = str(value or "").strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise CheckoutError("A valid customer email is required.")
    return value


@dataclass(frozen=True)
class Settings:
    secret_key: str
    webhook_secret: str
    price_id: str
    db_path: Path
    package_path: Path
    success_url: str
    cancel_url: str
    mode: str = "test"
    max_downloads: int = 3
    token_ttl_seconds: int = 7 * 24 * 3600

    def validate(self) -> None:
        if self.mode != "test":
            raise CheckoutError("VoiceLedger checkout is TEST-only.")
        if not self.secret_key.startswith("sk_test_") or len(self.secret_key) < 12:
            raise CheckoutError("Only Stripe TEST secret keys are accepted.")
        if not self.webhook_secret.startswith("whsec_") or len(self.webhook_secret) < 12:
            raise CheckoutError("A dedicated Stripe webhook secret is required.")
        if not re.fullmatch(r"price_[a-zA-Z0-9_]+", self.price_id):
            raise CheckoutError("Specify an existing Stripe TEST price ID.")
        for url in (self.success_url, self.cancel_url):
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                raise CheckoutError("Checkout redirects must use trusted HTTPS URLs.")
            if parts.hostname in {"localhost", "127.0.0.1"}:
                raise CheckoutError("Use HTTPS staging URLs for checkout redirects.")
        if self.max_downloads < 1 or not 60 <= self.token_ttl_seconds <= 30 * 24 * 3600:
            raise CheckoutError("Invalid token delivery policy.")
        if not self.package_path.is_file() or self.package_path.stat().st_size > 30 * 1024 * 1024:
            raise CheckoutError("A private licensed delivery package (up to 30 MB) is required.")

    @classmethod
    def from_env(cls) -> "Settings":
        required = ("VL_STRIPE_TEST_SECRET", "VL_STRIPE_WEBHOOK_SECRET", "VL_STRIPE_TEST_PRICE_ID",
                    "VL_DATABASE_PATH", "VL_PRIVATE_PACKAGE_PATH", "VL_CHECKOUT_SUCCESS_URL",
                    "VL_CHECKOUT_CANCEL_URL")
        if any(not os.getenv(k, "").strip() for k in required):
            raise CheckoutError("VoiceLedger commerce is disabled: explicit TEST configuration is required.")
        config = cls(
            secret_key=os.environ["VL_STRIPE_TEST_SECRET"].strip(),
            webhook_secret=os.environ["VL_STRIPE_WEBHOOK_SECRET"].strip(),
            price_id=os.environ["VL_STRIPE_TEST_PRICE_ID"].strip(),
            db_path=Path(os.environ["VL_DATABASE_PATH"]),
            package_path=Path(os.environ["VL_PRIVATE_PACKAGE_PATH"]),
            success_url=os.environ["VL_CHECKOUT_SUCCESS_URL"].strip(),
            cancel_url=os.environ["VL_CHECKOUT_CANCEL_URL"].strip(),
            mode=os.getenv("VL_CHECKOUT_MODE", "disabled"),
        )
        config.validate()
        return config


class StripeGateway:
    """Small dedicated Stripe TEST API client. Never falls back to a live key."""

    def __init__(self, config: Settings):
        config.validate()
        self.config = config

    def _request(self, method: str, path: str, params: dict[str, str] | None = None) -> dict:
        url = "https://api.stripe.com/v1/" + path
        data = None
        if method == "GET" and params:
            url += "?" + urlencode(params)
        elif method == "POST":
            data = urlencode(params or {}).encode("utf-8")
        req = Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.config.secret_key,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            with urlopen(req, timeout=15) as response:
                result = json.loads(response.read(512 * 1024))
        except Exception as exc:
            # Avoid logging secrets or copying Stripe's sensitive error body.
            raise CheckoutError("Stripe TEST API was unavailable.") from exc
        if not isinstance(result, dict):
            raise CheckoutError("Stripe TEST API returned an unexpected response.")
        return result

    def create(self, email: str, order_id: str) -> dict:
        return self._request("POST", "checkout/sessions", {
            "mode": "payment",
            "line_items[0][price]": self.config.price_id,
            "line_items[0][quantity]": "1",
            "customer_email": email,
            "client_reference_id": order_id,
            "metadata[sku]": SKU,
            "metadata[order_id]": order_id,
            "success_url": self.config.success_url,
            "cancel_url": self.config.cancel_url,
            "payment_method_types[0]": "card",
        })

    def retrieve(self, session_id: str) -> dict:
        return self._request("GET", "checkout/sessions/" + session_id, {
            "expand[0]": "line_items",
        })


def validate_webhook(raw: bytes, signature: str, secret: str, *, now: int | None = None) -> dict:
    if len(raw) > 1024 * 1024:
        raise CheckoutError("Webhook payload too large.")
    fields = {}
    signatures = []
    for piece in signature.split(","):
        key, sep, value = piece.partition("=")
        if sep and key == "v1":
            signatures.append(value)
        elif sep and key == "t":
            fields[key] = value
    try:
        stamp = int(fields["t"])
    except (ValueError, KeyError):
        raise CheckoutError("Missing webhook timestamp.") from None
    now = int(time.time()) if now is None else now
    if abs(now - stamp) > 300:
        raise CheckoutError("Webhook timestamp is outside the allowed window.")
    expected = hmac.new(secret.encode(), str(stamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, signature_value) for signature_value in signatures):
        raise CheckoutError("Webhook signature verification failed.")
    try:
        event = json.loads(raw)
    except (ValueError, UnicodeError):
        raise CheckoutError("Malformed webhook JSON.") from None
    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
        raise CheckoutError("Malformed Stripe event.")
    if event.get("livemode") is not False:
        raise CheckoutError("Live Stripe events are forbidden.")
    return event


class Commerce:
    def __init__(self, settings: Settings, gateway: StripeGateway | None = None):
        settings.validate()
        self.settings = settings
        self.gateway = gateway if gateway is not None else StripeGateway(settings)
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_database()

    def db(self):
        connection = sqlite3.connect(str(self.settings.db_path), timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def init_database(self):
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    session_id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    created_at INTEGER NOT NULL, paid_at INTEGER);
                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, processed_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS entitlements (
                    session_id TEXT PRIMARY KEY REFERENCES orders(session_id),
                    token_hash TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL,
                    download_count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS delivery_outbox (
                    session_id TEXT PRIMARY KEY REFERENCES orders(session_id),
                    email TEXT NOT NULL, token TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                    created_at INTEGER NOT NULL);
            """)

    def start_checkout(self, email: str) -> dict:
        email = email_normalized(email)
        order_id = uuid4().hex
        session = self.gateway.create(email, order_id)
        sid = session.get("id", "")
        url = session.get("url", "")
        if not isinstance(sid, str) or not re.fullmatch(r"cs_test_[a-zA-Z0-9_]+", sid):
            raise CheckoutError("Stripe did not return a TEST Checkout Session.")
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or parsed.hostname != "checkout.stripe.com":
            raise CheckoutError("Stripe did not return a trusted hosted Checkout URL.")
        with self.db() as db:
            db.execute("INSERT INTO orders (session_id,order_id,email,created_at) VALUES (?,?,?,?)",
                       (sid, order_id, email, int(time.time())))
        return {"session_id": sid, "url": url, "mode": "test"}

    def _validate_paid_session(self, session: dict, row: sqlite3.Row) -> None:
        if session.get("id") != row["session_id"] or session.get("livemode") is not False:
            raise CheckoutError("Session does not match a Stripe TEST order.")
        if session.get("status") != "complete" or session.get("payment_status") != "paid":
            raise CheckoutError("Checkout payment has not completed.")
        if session.get("mode") != "payment":
            raise CheckoutError("Unexpected Checkout mode.")
        if session.get("client_reference_id") != row["order_id"]:
            raise CheckoutError("Checkout order ID mismatch.")
        meta = session.get("metadata") or {}
        if meta.get("sku") != SKU or meta.get("order_id") != row["order_id"]:
            raise CheckoutError("Product/order metadata mismatch.")
        details = session.get("customer_details") or {}
        actual_email = details.get("email") or session.get("customer_email")
        if email_normalized(actual_email) != row["email"]:
            raise CheckoutError("Customer email mismatch.")
        items = (session.get("line_items") or {}).get("data") or []
        if len(items) != 1 or (session.get("line_items") or {}).get("has_more") or items[0].get("quantity") != 1:
            raise CheckoutError("Expected exactly one VoiceLedger license.")
        price = items[0].get("price") or {}
        if price.get("id") != self.settings.price_id or price.get("currency") != "usd":
            raise CheckoutError("Wrong TEST price or currency.")
        if price.get("unit_amount") != PRICE_CENTS or price.get("type") != "one_time":
            raise CheckoutError("The proposed VoiceLedger price must match USD $39 one-time.")

    def receive_webhook(self, raw: bytes, header: str, *, now: int | None = None) -> str:
        event = validate_webhook(raw, header, self.settings.webhook_secret, now=now)
        event_type = event.get("type", "")
        if event_type not in EVENTS:
            return "ignored"
        obj = ((event.get("data") or {}).get("object") or {})
        session_id = obj.get("id", "")
        if not isinstance(session_id, str) or not re.fullmatch(r"cs_test_[a-zA-Z0-9_]+", session_id):
            raise CheckoutError("Unexpected session ID.")
        with self.db() as db:
            row = db.execute("SELECT * FROM orders WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            raise CheckoutError("Checkout session was not created by this service.")
        # Retrieve from Stripe server-side. Never trust a browser redirect, or the
        # event's copy of payment status, as proof of purchase.
        session = self.gateway.retrieve(session_id)
        if session.get("payment_status") != "paid":
            return "awaiting_payment"
        self._validate_paid_session(session, row)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        timestamp = int(time.time()) if now is None else now
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM webhook_events WHERE event_id=?", (event["id"],)).fetchone():
                db.rollback()
                return "duplicate_event"
            db.execute("INSERT INTO webhook_events VALUES (?,?,?)", (event["id"], event_type, timestamp))
            already = db.execute("SELECT 1 FROM entitlements WHERE session_id=?", (session_id,)).fetchone()
            if not already:
                db.execute("UPDATE orders SET state='paid',paid_at=? WHERE session_id=?",
                           (timestamp, session_id))
                db.execute("INSERT INTO entitlements (session_id,token_hash,expires_at) VALUES (?,?,?)",
                           (session_id, token_hash, timestamp + self.settings.token_ttl_seconds))
                db.execute("INSERT INTO delivery_outbox (session_id,email,token,created_at) VALUES (?,?,?,?)",
                           (session_id, row["email"], token, timestamp))
            db.commit()
        return "already_fulfilled" if already else "queued_for_delivery"

    def status(self, session_id: str) -> dict:
        if not re.fullmatch(r"cs_test_[a-zA-Z0-9_]+", session_id):
            raise CheckoutError("Unknown TEST checkout session.")
        with self.db() as db:
            row = db.execute("SELECT state FROM orders WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            raise CheckoutError("Unknown TEST checkout session.")
        return {"status": row["state"], "delivery": "manual_test_outbox_only"}

    def download(self, token: str) -> bytes:
        if not isinstance(token, str) or len(token) < 35 or len(token) > 128:
            raise CheckoutError("Invalid delivery token.")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM entitlements WHERE token_hash=?", (token_hash,)).fetchone()
            if not row or row["expires_at"] <= int(time.time()) or row["download_count"] >= self.settings.max_downloads:
                db.rollback()
                raise CheckoutError("Delivery access expired or unavailable.")
            content = self.settings.package_path.read_bytes()
            db.execute("UPDATE entitlements SET download_count=download_count+1 WHERE token_hash=?",
                       (token_hash,))
            db.commit()
        return content
