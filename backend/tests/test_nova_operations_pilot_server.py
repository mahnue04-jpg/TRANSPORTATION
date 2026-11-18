"""Acceptance checks for isolated synthetic Operations CSV pilot."""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture
def pilot(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "operations_pilot_server.py"
    spec = importlib.util.spec_from_file_location("operations_pilot_server_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_PILOT_MODE", "staging-synthetic")
    monkeypatch.setenv("NOVA_OPERATIONS_PILOT_OWNER_TOKEN", "staging-example-owner-token-very-long-1234567")
    for name in (
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
    ):
        monkeypatch.setenv(name, "false")
    return module


@pytest.fixture
def server(pilot):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), pilot.PilotHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def valid_headers():
    return {
        "Authorization": "Bearer staging-example-owner-token-very-long-1234567",
        "X-Nova-Owner-Action": "process-csv-for-owner-review",
        "X-Nova-Synthetic-Data": "true",
        "Content-Type": "text/csv",
    }


def test_health_proves_processing_disabled(server):
    status, _, raw = request(server, "GET", "/health")
    assert status == 200
    assert json.loads(raw)["customer_processing"] is False


def test_supervised_synthetic_csv_cleanup_review_only(server):
    payload = b"name,city\nAda,Minneapolis\nAda,Minneapolis\nBob,St Paul\n"
    status, headers, body = request(
        server, "POST", "/operations/pilot/csv-clean",
        payload, valid_headers(),
    )
    assert status == 200
    assert body == b"name,city\nAda,Minneapolis\nBob,St Paul\n"
    assert headers["X-Nova-Owner-Review-Required"] == "true"
    assert headers["X-Nova-Delivery-Status"] == "owner-review-only-not-delivered"
    assert headers["X-Nova-Customer-Delivery"] == "disabled"


@pytest.mark.parametrize("headers,expected", [
    ({}, 403),
    ({"Authorization": "Bearer wrong"}, 403),
    (dict(valid_headers(), **{"X-Nova-Synthetic-Data": "false"}), 403),
    (dict(valid_headers(), **{"X-Nova-Owner-Action": "wrong"}), 403),
])
def test_no_unauthorized_processing(server, headers, expected):
    status, _, _ = request(server, "POST", "/operations/pilot/csv-clean", b"a\nb\n", headers)
    assert status == expected


def test_customer_routes_disabled(server):
    assert request(server, "GET", "/operations/queued/jobs/example")[0] == 503
    assert request(server, "POST", "/operations/queued/jobs/example", b"x")[0] == 503


def test_bad_data_rejected(server):
    headers = valid_headers()
    assert request(server, "POST", "/operations/pilot/csv-clean", b"", headers)[0] == 413
    assert request(server, "POST", "/operations/pilot/csv-clean", b"bad\xff", headers)[0] == 400


def test_staging_runtime_restrictions(pilot, monkeypatch):
    pilot._validate_runtime()
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="staging"):
        pilot._validate_runtime()
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    with pytest.raises(RuntimeError, match="disabled"):
        pilot._validate_runtime()
