"""Isolated HTTP integration checks: no Stripe requests, charges or customer data."""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import time
from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient
from flow import Commerce, Settings
import api
from test_flow import FakeStripe


class CheckoutHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        package = folder / "private.zip"
        package.write_bytes(b"test ZIP content")
        settings = Settings(
            secret_key="sk_test_testing_only",
            webhook_secret="whsec_testing_only",
            price_id="price_voiceledger_test",
            db_path=folder / "commerce.sqlite3",
            package_path=package,
            success_url="https://stage.example.com/complete",
            cancel_url="https://stage.example.com/cancel",
            max_downloads=1,
        )
        self.fake = FakeStripe(settings)
        self.service = Commerce(settings, self.fake)
        api._service = self.service
        self.addCleanup(lambda: setattr(api, "_service", None))
        self.client = TestClient(api.app)

    def event(self, event_id="evt_test_123"):
        payload = {
            "id": event_id,
            "livemode": False,
            "type": "checkout.session.completed",
            "data": {"object": {"id": self.fake.session["id"]}},
        }
        raw = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        digest = hmac.new(
            self.service.settings.webhook_secret.encode(),
            timestamp.encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        return raw, "t=" + timestamp + ",v1=" + digest

    def test_checkout_creates_test_session_without_granting_access(self):
        response = self.client.post("/api/voiceledger/checkout", json={"email": "buyer@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "test")
        self.assertTrue(response.json()["url"].startswith("https://checkout.stripe.com/"))
        check = self.client.get("/api/voiceledger/orders/" + response.json()["session_id"])
        self.assertEqual(check.json()["status"], "pending")
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0], 0)

    def test_unpaid_webhook_no_delivery_then_paid_download_once(self):
        self.client.post("/api/voiceledger/checkout", json={"email": "buyer@example.com"})
        raw, sig = self.event()
        pending = self.client.post("/api/voiceledger/stripe/webhook", content=raw, headers={"Stripe-Signature": sig})
        self.assertEqual(pending.json()["processed"], "awaiting_payment")
        self.fake.session["status"] = "complete"
        self.fake.session["payment_status"] = "paid"
        accepted = self.client.post("/api/voiceledger/stripe/webhook", content=raw, headers={"Stripe-Signature": sig})
        self.assertEqual(accepted.json()["processed"], "queued_for_delivery")
        repeat = self.client.post("/api/voiceledger/stripe/webhook", content=raw, headers={"Stripe-Signature": sig})
        self.assertEqual(repeat.json()["processed"], "duplicate_event")
        with self.service.db() as db:
            row = db.execute("SELECT token,email FROM delivery_outbox").fetchone()
        self.assertEqual(row["email"], "buyer@example.com")
        self.assertNotIn(row["token"], str(accepted.json()))
        self.assertNotIn(row["token"], str(self.client.get("/api/voiceledger/orders/" + self.fake.session["id"]).json()))
        downloaded = self.client.get("/api/voiceledger/download/" + row["token"])
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, b"test ZIP content")
        self.assertIn("attachment;", downloaded.headers["content-disposition"])
        self.assertEqual(downloaded.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/api/voiceledger/download/" + row["token"]).status_code, 404)

    def test_invalid_or_unpaid_requests_fail(self):
        self.client.post("/api/voiceledger/checkout", json={"email": "buyer@example.com"})
        raw, sig = self.event()
        self.assertEqual(self.client.post("/api/voiceledger/stripe/webhook", content=raw).status_code, 400)
        self.assertEqual(self.client.post("/api/voiceledger/stripe/webhook", content=raw, headers={"Stripe-Signature": "bad"}).status_code, 400)
        self.assertEqual(self.client.get("/api/voiceledger/download/fake").status_code, 404)
        self.assertEqual(self.client.get("/api/voiceledger/orders/cs_test_missing").status_code, 404)
        self.assertEqual(self.client.post("/api/voiceledger/checkout", json={"email": "invalid"}).status_code, 400)

    def test_checkout_return_pages_never_deliver_unauthenticated_files(self):
        complete = self.client.get("/complete?session_id=cs_test_missing")
        self.assertEqual(complete.status_code, 200)
        self.assertIn("test-mode", complete.text)
        self.assertIn("No download has been released", complete.text)
        self.assertIn("no-store", complete.headers.get("cache-control", ""))
        self.assertIn("frame-ancestors", complete.headers.get("content-security-policy", ""))
        self.assertNotIn("sk_test_testing_only", complete.text)
        cancelled = self.client.get("/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertIn("cancelled", cancelled.text.lower())
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0], 0)

    def test_default_http_service_does_not_start(self):
        from unittest.mock import patch
        api._service = None
        with patch.dict("os.environ", {"VL_CHECKOUT_MODE": "disabled"}, clear=True):
            result = self.client.post("/api/voiceledger/checkout", json={"email": "buyer@example.com"})
        self.assertEqual(result.status_code, 503)


if __name__ == "__main__":
    unittest.main()
