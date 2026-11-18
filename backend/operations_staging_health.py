"""Read-only Operations staging smoke server. No shared AMICOR app imports.

This server intentionally does not import app.main, SQLAlchemy, boto3, or
payment/worker modules. It can ONLY check the deployed Python runtime and
signal that all customer operations remain disabled. It must never be used
as proof of a functioning customer workflow.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class DiagnosticHandler(BaseHTTPRequestHandler):
    server_version = "NovaOperationsStagingDiagnostic"
    sys_version = ""

    def _respond(self, status: int, *, include_body: bool) -> None:
        healthy = self.path in ("/health", "/health/")
        if healthy and status == 200:
            payload = {
                "status": "diagnostic_only",
                "customer_processing": False,
                "database_connected": False,
                "private_storage_connected": False,
                "worker_enabled": False,
            }
        else:
            payload = {
                "status": "disabled",
                "customer_processing": False,
            }
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def do_GET(self) -> None:
        self._respond(200 if self.path in ("/health", "/health/") else 503,
                      include_body=True)

    def do_HEAD(self) -> None:
        self._respond(200 if self.path in ("/health", "/health/") else 503,
                      include_body=False)

    def do_POST(self) -> None:
        self._respond(503, include_body=True)

    def do_PUT(self) -> None:
        self._respond(503, include_body=True)

    def do_DELETE(self) -> None:
        self._respond(503, include_body=True)


def serve(*, host: str = "0.0.0.0", port: int | None = None) -> None:
    if os.getenv("NOVA_OPERATIONS_STAGING_DIAGNOSTIC_ONLY", "").lower() != "true":
        raise RuntimeError("Explicit diagnostic-only staging flag required")
    if os.getenv("AMICOR_ENVIRONMENT", "").lower() != "staging":
        raise RuntimeError("Staging environment required")
    if any(os.getenv(flag, "").lower() in ("1", "true", "yes") for flag in (
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
    )):
        raise RuntimeError("Customer work or private storage must remain disabled")
    chosen_port = int(port if port is not None else os.environ.get("PORT", "10000"))
    if not 1 <= chosen_port <= 65535:
        raise ValueError("Invalid diagnostic port")
    server = ThreadingHTTPServer((host, chosen_port), DiagnosticHandler)
    server.serve_forever()


if __name__ == "__main__":
    serve()
