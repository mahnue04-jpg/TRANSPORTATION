"""Synthetic no-provider acceptance for the Operations read-only staging server."""
from __future__ import annotations

import ast
import http.client
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "operations_staging_health.py"


def load_diagnostic():
    spec = importlib.util.spec_from_file_location("operations_staging_health", FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_isolated_health_server_never_imports_customer_application():
    source = FILE.read_text(encoding="utf-8")
    # Inspect actual syntax, not docstring/comment text mentioning app imports.
    imports = []
    for node in ast.walk(ast.parse(source, filename=str(FILE))):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    allowed = {"__future__", "json", "os", "http.server"}
    assert set(imports).issubset(allowed), imports
    assert "app.main" not in sys.modules
    module = load_diagnostic()
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.DiagnosticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        for method, path, expected in [
            ("GET", "/health", 200),
            ("HEAD", "/health", 200),
            ("GET", "/operations/queued/jobs/anything", 503),
            ("POST", "/operations/queued/jobs/anything", 503),
            ("PUT", "/health", 503),
            ("DELETE", "/health", 503),
        ]:
            conn.request(method, path)
            resp = conn.getresponse()
            body = resp.read()
            assert resp.status == expected
            assert resp.getheader("Cache-Control") == "no-store"
            assert resp.getheader("X-Content-Type-Options") == "nosniff"
            if method != "HEAD":
                result = json.loads(body)
                assert result["customer_processing"] is False
                if path == "/health" and method == "GET":
                    assert result["status"] == "diagnostic_only"
                    assert result["database_connected"] is False
                    assert result["private_storage_connected"] is False
            else:
                assert body == b""
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("overrides", [
    {"AMICOR_ENVIRONMENT": "production"},
    {"NOVA_OPERATIONS_STAGING_DIAGNOSTIC_ONLY": "false"},
    {"NOVA_OPERATIONS_LEASE_WORKER_ENABLED": "true"},
    {"NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED": "true"},
    {"NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED": "true"},
])
def test_staging_entrypoint_fails_closed_before_binding_socket(overrides):
    env = dict(os.environ)
    env.update({
        "AMICOR_ENVIRONMENT": "staging",
        "NOVA_OPERATIONS_STAGING_DIAGNOSTIC_ONLY": "true",
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED": "false",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED": "false",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED": "false",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED": "false",
    })
    env.update(overrides)
    code = (
        "import operations_staging_health as m; "
        "m.serve(host='127.0.0.1', port=0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, env=env, capture_output=True, text=True,
        timeout=5, check=False,
    )
    assert completed.returncode != 0
    assert "RuntimeError" in completed.stderr
    assert "staging" in completed.stderr.lower() or "disabled" in completed.stderr.lower()
