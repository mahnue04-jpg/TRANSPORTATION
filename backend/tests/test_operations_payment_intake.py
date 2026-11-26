import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch

import psycopg2
from fastapi.testclient import TestClient

from operations_payment_intake import app


class PaymentIntakeTest(unittest.TestCase):
    def test_signed_redelivery_and_rejection(self):
        secret = "whsec_synthetic_ci"
        event = {"id": "evt_ci", "object": "event", "type": "invoice.paid",
                 "livemode": True, "data": {"object": {"id": "in_ci", "object": "invoice"}}}
        client = TestClient(app)
        def send():
            data = json.dumps(event).encode()
            stamp = str(int(time.time()))
            digest = hmac.new(secret.encode(), stamp.encode() + b"." + data, hashlib.sha256).hexdigest()
            return client.post("/payments/stripe/webhook", content=data,
                               headers={"stripe-signature": f"t={stamp},v1={digest}"})
        with patch.dict(os.environ, NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET=secret):
            self.assertEqual(client.post("/payments/stripe/webhook").status_code, 400)
            self.assertEqual(send().status_code, 200)
            self.assertEqual(send().status_code, 200)
            event["livemode"] = False
            self.assertEqual(send().status_code, 400)
        conn = psycopg2.connect(os.environ["NOVA_OPERATIONS_DATABASE_URL"])
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT event_id, object_id FROM nova_operations_payment_events")
                self.assertEqual(cursor.fetchall(), [("evt_ci", "in_ci")])
        finally:
            conn.close()
