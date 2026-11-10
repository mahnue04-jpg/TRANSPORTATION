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



def test_saved_job_history_controls_and_reopen_endpoint():
    for element_id in (
        "operations-durable-history-refresh",
        "operations-durable-history-select",
        "operations-durable-history-open",
        "operations-durable-history-result",
    ):
        assert f'id="{element_id}"' in HTML
    assert '"/api/nova/work/operations/durable/jobs"' in JS
    assert "await refreshJobStatus()" in JS
    assert "No customer delivery" in JS


def test_staging_recovery_rehearsal_ui_is_owner_scoped_and_non_delivery():
    preview_html = (UI / "recovery-preview.html").read_text(encoding="utf-8")
    preview_js = (UI / "recovery-preview.js").read_text(encoding="utf-8")
    assert "Staging only. Use fictional CSV data." in preview_html
    for element_id in (
        "recovery-load-tasks", "recovery-task-select", "recovery-upload-form",
        "recovery-load-history", "recovery-job-select", "recovery-process",
        "recovery-check", "recovery-download", "recovery-approve", "recovery-reject",
    ):
        assert f'id="{element_id}"' in preview_html
    for route in ("/eligible-csv-tasks", "/jobs", "/process", "/review", "/download"):
        assert route in preview_js
    assert 'session.getAuthHeaders' in preview_js
    assert 'Not delivered' in preview_js
