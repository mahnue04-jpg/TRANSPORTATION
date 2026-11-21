"""Offline tests for isolated Nova Intelligence evidence timeline."""
import unittest

from app.core.nova.intelligence.timeline import TimedObservation, timeline


class TimelineTests(unittest.TestCase):
    def test_sorts_and_retains_provenance(self):
        events = [
            TimedObservation(8.0, 8.0, "frame_ocr", "Agenda", "frame:8"),
            TimedObservation(1.0, 3.0, "transcript", "Welcome", "audio:1-3"),
        ]
        result = timeline(events)
        self.assertEqual([x["source_ref"] for x in result], ["audio:1-3", "frame:8"])

    def test_rejects_invalid_timestamps(self):
        for value in (-1.0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                TimedObservation(value, 3.0, "scene", "Summary", "scene:1")

    def test_rejects_missing_provenance(self):
        with self.assertRaises(ValueError):
            TimedObservation(0.0, 1.0, "scene", "Summary", "")

    def test_never_invents_observations(self):
        self.assertEqual(timeline([]), [])


if __name__ == "__main__":
    unittest.main()
