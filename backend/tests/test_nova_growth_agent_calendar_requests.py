"""Dependency-free request contracts, not live Google or application acceptance."""

import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

# Load only the pure module; app.core.nova imports unrelated application routers.
SOURCE = Path(__file__).parents[1] / "app/core/nova/growth_agent/providers/google_calendar_requests.py"
spec = importlib.util.spec_from_file_location("nova_calendar_requests_contract", SOURCE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class CalendarRequestTests(unittest.TestCase):
    def setUp(self):
        self.binding = module.CalendarBinding("org-a", "owner+calendar@example.invalid")
        self.start = datetime(2026, 11, 20, 10, tzinfo=timezone(timedelta(hours=-6)))
        self.end = self.start + timedelta(minutes=30)

    def prepare(self, action="create", **overrides):
        args = dict(binding=self.binding, organization_id="org-a", appointment_id="appt-1", action=action)
        if action != "cancel":
            args.update(starts_at=self.start, ends_at=self.end)
        args.update(overrides)
        return module.prepare_calendar_request(**args)

    def test_create_converts_to_utc_without_attendees_or_contact_details(self):
        request = self.prepare()
        body = json.loads(request.body_json)
        self.assertEqual(request.method, "POST")
        self.assertEqual(body["start"]["dateTime"], "2026-11-20T16:00:00Z")
        self.assertEqual(set(body), {"id", "summary", "start", "end"})
        self.assertEqual(request.send_updates, "none")

    def test_lifecycle_uses_same_event_and_reschedule_preserves_other_fields(self):
        create = self.prepare()
        reschedule = self.prepare("reschedule", starts_at=self.start + timedelta(days=1), ends_at=self.end + timedelta(days=1))
        cancel = self.prepare("cancel")
        event_id = json.loads(create.body_json)["id"]
        self.assertEqual(reschedule.path, create.path + "/" + event_id)
        self.assertEqual(cancel.path, reschedule.path)
        self.assertEqual(reschedule.method, "PATCH")
        self.assertEqual(set(json.loads(reschedule.body_json)), {"start", "end"})
        self.assertEqual(cancel.method, "DELETE")
        self.assertIsNone(cancel.body_json)

    def test_create_retry_is_identical(self):
        self.assertEqual(self.prepare(), self.prepare())

    def test_ids_are_valid_distinct_and_framed(self):
        event_id = module.event_id_for("org-a", "appt-1")
        self.assertTrue(re.fullmatch(r"[0-9a-v]{5,1024}", event_id))
        self.assertNotEqual(event_id, module.event_id_for("org-b", "appt-1"))
        self.assertNotEqual(event_id, module.event_id_for("org-a", "appt-2"))
        self.assertNotEqual(module.event_id_for("a|b", "c"), module.event_id_for("a", "b|c"))

    def test_tenant_mismatch_denied_for_every_action(self):
        for action in ("create", "reschedule", "cancel"):
            with self.subTest(action=action), self.assertRaisesRegex(module.CalendarRequestError, "^TENANT_MISMATCH$"):
                self.prepare(action, organization_id="org-b")

    def test_naive_and_missing_times_denied(self):
        for field in ("starts_at", "ends_at"):
            for value in (None, datetime(2026, 11, 20, 10), "2026-11-20T10:00:00Z"):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(module.CalendarRequestError, "^TIMEZONE_REQUIRED$"):
                    self.prepare(**{field: value})

    def test_invalid_range_denied(self):
        for end in (self.start, self.start - timedelta(minutes=1)):
            with self.subTest(end=end), self.assertRaisesRegex(module.CalendarRequestError, "^INVALID_TIME_RANGE$"):
                self.prepare(ends_at=end)

    def test_unsupported_actions_denied(self):
        for action in ("delete_all", "", "CREATE"):
            with self.subTest(action=action), self.assertRaisesRegex(module.CalendarRequestError, "^INVALID_ACTION$"):
                self.prepare(action)

    def test_invalid_identifiers_do_not_leak_input(self):
        for value in ("", "   ", "secret\n", None, "x" * 1025):
            with self.subTest(value=value), self.assertRaisesRegex(module.CalendarRequestError, "^INVALID_APPOINTMENT$"):
                self.prepare(appointment_id=value)

    def test_global_or_invalid_binding_denied(self):
        for org in ("*", "global", "ALL", "", None):
            with self.subTest(org=org), self.assertRaisesRegex(module.CalendarRequestError, "^INVALID_BINDING$"):
                module.CalendarBinding(org, "calendar")

    def test_calendar_id_cannot_inject_path_or_query(self):
        request = self.prepare(binding=module.CalendarBinding("org-a", "a/b?sendUpdates=all#x"))
        self.assertEqual(request.path, "/calendars/a%2Fb%3FsendUpdates%3Dall%23x/events")

    def test_cancel_rejects_ambiguous_time_payload(self):
        with self.assertRaisesRegex(module.CalendarRequestError, "^UNEXPECTED_TIME_RANGE$"):
            self.prepare("cancel", starts_at=self.start)


if __name__ == "__main__":
    unittest.main()
