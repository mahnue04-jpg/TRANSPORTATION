"""Static contract checks for durable CSV owner UI wiring (not browser tests)."""
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "static" / "nova-work"
JS = (UI / "operations-csv.js").read_text(encoding="utf-8")
HTML = (UI / "index.html").read_text(encoding="utf-8")


def test_durable_csv_ui_controls_are_present():
    for element_id in (
        "operations-eligible-select",
        "operations-scoped-csv-form",
        "operations-durable-status",
        "operations-durable-download",
        "operations-durable-approve",
        "operations-durable-reject",
    ):
        assert f'id="{element_id}"' in HTML
    assert 'id="operations-engagement-id"' not in HTML
    assert 'id="operations-task-id"' not in HTML


def test_owner_ui_targets_gated_durable_api():
    assert "/api/nova/work/operations/durable/engagements/" in JS
    assert 'jobPath("/download")' in JS
    assert 'jobPath("/review")' in JS
    assert '"Idempotency-Key": currentRequest.key' in JS
    assert '"X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization"' in JS
    assert "A CSV job request is already running" in JS


def test_no_automatic_customer_delivery_claim():
    assert "No customer delivery or payment occurred." in JS
    assert "Not delivered to a client." in JS
    assert "Owner review is not customer delivery" in HTML
