"""Focused non-network tests for VoiceLedger TEST checkout and private fulfillment."""
import hashlib
import hmac
import json
import tempfile
import time
from pathlib import Path
import unittest

from flow import CheckoutError, Commerce, Settings, validate_webhook


class FakeStripe:
    def __init__(self, config):
        self.config = config
        self.session = None
        self.retrieved = 0

    def create(self, email, order_id):
        sid = "cs_test_voiceledger_purchase_1"
        self.session = {
            "id": sid, "livemode": False, "status": "open", "payment_status": "unpaid",
            "mode": "payment", "client_reference_id": order_id,
            "customer_email": email,
            "metadata": {"sku": "voiceledger_pro", "order_id": order_id},
            "line_items": {"data": [
                {"quantity": 1, "price": {"id": self.config.price_id, "currency": "usd",
                                          "unit_amount": 3900, "type": "one_time"}}
            ], "has_more": False},
            "url": "https://checkout.stripe.com/c/pay/cs_test_voiceledger_purchase_1",
        }
        return dict(self.session)

    def retrieve(self, session_id):
        self.retrieved += 1
        if session_id != self.session["id"]:
            raise CheckoutError("Unknown session.")
        return dict(self.session)


def signed_event(secret, event_id="evt_test_paid", sid="cs_test_voiceledger_purchase_1", event_type="checkout.session.completed", ts=None, livemode=False):
    ts = ts or int(time.time())
    raw = json.dumps({"id": event_id, "type": event_type, "livemode": livemode,
                      "data": {"object": {"id": sid}}}).encode()
    sig = hmac.new(secret.encode(), str(ts).encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, f"t={ts},v1={sig}"


class CommerceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        package = root / "licensed.zip"
        package.write_bytes(b"fake licensed ZIP for local tests only")
        self.config = Settings(
            secret_key="sk_test_testing_only", webhook_secret="whsec_testing_only",
            price_id="price_test_voiceledger", db_path=root / "orders.sqlite3",
            package_path=package,
            success_url="https://staging.example.com/complete",
            cancel_url="https://staging.example.com/cancel",
            max_downloads=1,
        )
        self.fake = FakeStripe(self.config)
        self.store = Commerce(self.config, self.fake)
        self.order = self.store.start_checkout("  customer@example.com  ")

    def paid(self):
        self.fake.session["payment_status"] = "paid"
        self.fake.session["status"] = "complete"

    def test_start_is_test_only_and_no_fulfillment(self):
        self.assertTrue(self.order["session_id"].startswith("cs_test_"))
        self.assertEqual(self.store.status(self.order["session_id"])["status"], "pending")
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0], 0)

    def test_signed_webhook_requires_actual_verified_payment(self):
        raw, sig = signed_event(self.config.webhook_secret)
        self.assertEqual(self.store.receive_webhook(raw, sig), "awaiting_payment")
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0], 0)
        self.paid()
        self.assertEqual(self.store.receive_webhook(raw, sig), "queued_for_delivery")
        self.assertEqual(self.store.status(self.order["session_id"])["status"], "paid")
        self.assertEqual(self.store.receive_webhook(raw, sig), "duplicate_event")
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM delivery_outbox").fetchone()[0], 1)

    def test_signed_event_with_second_event_id_cannot_duplicate_delivery(self):
        self.paid()
        raw, sig = signed_event(self.config.webhook_secret, "evt_first")
        raw2, sig2 = signed_event(self.config.webhook_secret, "evt_second")
        self.assertEqual(self.store.receive_webhook(raw, sig), "queued_for_delivery")
        self.assertEqual(self.store.receive_webhook(raw2, sig2), "already_fulfilled")
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM delivery_outbox").fetchone()[0], 1)

    def test_private_delivery_token_expires_after_limit(self):
        self.paid()
        raw, sig = signed_event(self.config.webhook_secret)
        self.store.receive_webhook(raw, sig)
        with self.store.db() as db:
            token = db.execute("SELECT token FROM delivery_outbox").fetchone()[0]
        self.assertEqual(self.store.download(token), b"fake licensed ZIP for local tests only")
        with self.assertRaises(CheckoutError):
            self.store.download(token)
        with self.assertRaises(CheckoutError):
            self.store.download("not-valid")

    def test_invalid_signature_and_live_webhooks_fail_closed(self):
        raw, sig = signed_event(self.config.webhook_secret)
        with self.assertRaises(CheckoutError):
            validate_webhook(raw, "t=123,v1=deadbeef", self.config.webhook_secret)
        with self.assertRaises(CheckoutError):
            validate_webhook(raw, sig, "whsec_not_same")
        raw_live, sig_live = signed_event(self.config.webhook_secret, livemode=True)
        with self.assertRaises(CheckoutError):
            self.store.receive_webhook(raw_live, sig_live)

    def test_wrong_price_wrong_customer_wrong_quantity_are_rejected(self):
        self.paid()
        raw, sig = signed_event(self.config.webhook_secret)
        self.fake.session["line_items"]["data"][0]["price"]["unit_amount"] = 100
        with self.assertRaises(CheckoutError):
            self.store.receive_webhook(raw, sig)
        self.fake.session["line_items"]["data"][0]["price"]["unit_amount"] = 3900
        self.fake.session["customer_email"] = "wrong@example.com"
        with self.assertRaises(CheckoutError):
            self.store.receive_webhook(raw, sig)
        self.fake.session["customer_email"] = "customer@example.com"
        self.fake.session["line_items"]["has_more"] = True
        with self.assertRaises(CheckoutError):
            self.store.receive_webhook(raw, sig)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0], 0)

    def test_unapproved_live_key_rejected(self):
        bad = Settings(**{**vars(self.config), "secret_key": "sk_live_unsafe"})
        with self.assertRaises(CheckoutError):
            bad.validate()
        bad_mode = Settings(**{**vars(self.config), "mode": "live"})
        with self.assertRaises(CheckoutError):
            bad_mode.validate()

    def test_unknown_checkout_rejected(self):
        self.paid()
        raw, sig = signed_event(self.config.webhook_secret, sid="cs_test_other")
        with self.assertRaises(CheckoutError):
            self.store.receive_webhook(raw, sig)


if __name__ == "__main__":
    unittest.main()
