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
    assert '"/api/nova/work/operations/" + mode + "/engagements/"' in JS
    assert 'const mode = queued ? "queued" : "durable"' in JS
    assert 'jobPath("/download")' in JS
    assert 'jobPath("/review")' in JS
    assert '"Idempotency-Key": currentRequest.key' in JS
    assert '"X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization"' in JS
    assert "A CSV job request is already running" in JS


def test_no_automatic_customer_delivery_claim():
    assert "No customer delivery or payment occurred." in JS
    assert "Not delivered to a client." in JS
    assert "Owner review is not customer delivery" in HTML


def test_supervised_queued_ui_is_opt_in_and_explicit():
    assert 'id="operations-queued-mode"' in HTML
    assert 'id="operations-queued-process"' in HTML
    assert 'operations-queued-mode" />' in HTML
    assert 'const mode = queued ? "queued" : "durable"' in JS
    assert 'jobPath("/process")' in JS
    assert '"X-Nova-Owner-Action": "process-queued-csv-for-owner-review"' in JS
    assert '"X-Nova-Owner-Action": queued ? "queue-csv-for-owner-review"' in JS
    assert '"review-completed-queued-csv"' in JS
    assert 'currentLeaseStatus !== "QUEUED"' in JS
    assert "No customer delivery or payment occurred." in JS


def test_owner_recovery_and_cancel_are_explicit_and_safe():
    assert 'id="operations-queued-recovery"' in HTML
    assert 'id="operations-queued-cancel"' in HTML
    assert 'jobPath("/recovery")' in JS
    assert 'jobPath("/cancel")' in JS
    assert '"X-Nova-Owner-Action": "cancel-queued-csv-job"' in JS
    assert 'window.confirm("Cancel this queued job?' in JS
    assert 'No automatic retry or customer delivery.' in JS
    assert 'currentLeaseStatus !== "QUEUED"' in JS
    assert '["QUEUED", "RUNNING"].includes(currentLeaseStatus)' in JS


def test_scoped_csv_task_url_contains_both_escaped_identifiers():
    assert 'encodeURIComponent(selected.engagement_id) + "/tasks/" +' in JS
    assert 'encodeURIComponent(selected.task_id) + "/jobs"' in JS


def test_owner_restore_control_requires_explicit_recovery_diagnosis():
    assert 'id="operations-queued-restore"' in HTML
    assert 'currentRecoveryResult !== "input_binding_incomplete"' in JS
    assert 'jobPath("/restore-input")' in JS
    assert '"X-Nova-Owner-Action": "restore-unbound-csv-input"' in JS
    assert 'window.confirm("Restore the original CSV' in JS
    assert 'previous interrupted uploads may leave private objects' in JS.lower()
    assert 'currentRecoveryResult = result.recovery_result || ""' in JS
    assert 'currentRecoveryResult = ""' in JS
