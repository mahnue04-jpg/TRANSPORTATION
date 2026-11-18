"""Isolated supervised CSV pilot server. No app.main startup or database.

Synthetic staging ONLY. No customer intake, persistence, queue, storage,
payments, or automatic workers. Never use as public customer service before
separate real-data security, authorization and launch review.
"""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from app.core.nova.work_revenue.operations_csv_cleanup import (
    SpreadsheetInputError, clean_csv_text,
)

MAX_BYTES = 1_000_000
PATH = "/operations/pilot/csv-clean"


def _validate_runtime() -> str:
    if os.environ.get("AMICOR_ENVIRONMENT", "").lower() != "staging":
        raise RuntimeError("Isolated pilot requires staging")
    if os.environ.get("NOVA_OPERATIONS_PILOT_MODE") != "staging-synthetic":
        raise RuntimeError("Pilot must be explicitly synthetic-only")
    for name in ("NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
                 "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
                 "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
                 "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED"):
        if os.environ.get(name, "").lower() in ("true", "yes", "1"):
            raise RuntimeError("Workers, durable jobs and storage must stay disabled")
    token = os.environ.get("NOVA_OPERATIONS_PILOT_OWNER_TOKEN", "")
    if len(token) < 32 or len(token) > 512 or not token.isascii():
        raise RuntimeError("A strong owner-only secret is required")
    return token


class PilotHandler(BaseHTTPRequestHandler):
    server_version = "NovaOperationsPilot"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        # Avoid accidental logging of secret headers, URLs or CSV payloads.
        pass

    def _send(self, status: int, body: bytes, content_type="application/json",
              *, head=False, extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Nova-Customer-Delivery", "disabled")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _error(self, status: int, detail: str) -> None:
        self._send(status, json.dumps({"status": "blocked", "detail": detail}).encode())

    def do_GET(self):
        path = urlsplit(self.path).path
        if path != "/health":
            return self._error(503, "Customer routes disabled")
        self._send(200, json.dumps({
            "status": "synthetic_supervised_pilot",
            "customer_processing": False,
            "database_connected": False,
            "private_storage_connected": False,
            "worker_enabled": False,
        }).encode())

    def do_HEAD(self):
        if urlsplit(self.path).path != "/health":
            return self._send(503, b"", head=True)
        return self._send(200, b"", head=True)

    def do_POST(self):
        if urlsplit(self.path).path != PATH:
            return self._error(503, "Customer routes disabled")
        try:
            configured_token = _validate_runtime()
        except RuntimeError:
            return self._error(503, "Pilot not configured")
        presented = self.headers.get("Authorization", "")
        expected = "Bearer " + configured_token
        if not hmac.compare_digest(presented, expected):
            return self._error(403, "Owner authorization required")
        if (self.headers.get("X-Nova-Owner-Action", "") !=
                "process-csv-for-owner-review"):
            return self._error(403, "Explicit owner review action required")
        if self.headers.get("X-Nova-Synthetic-Data", "").lower() != "true":
            return self._error(403, "Only declared synthetic staging data accepted")
        if (self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                != "text/csv"):
            return self._error(415, "Only text/csv accepted")
        if self.headers.get("Transfer-Encoding"):
            return self._error(400, "Chunked bodies unsupported")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._error(411, "Content-Length required")
        if not 0 < length <= MAX_BYTES:
            return self._error(413, "CSV must be 1 to 1000000 bytes")
        raw = self.rfile.read(length)
        if len(raw) != length:
            return self._error(400, "Incomplete CSV")
        try:
            cleaned = clean_csv_text(raw.decode("utf-8-sig", "strict"),
                                     max_bytes=MAX_BYTES, max_rows=10_000)
        except (UnicodeError, SpreadsheetInputError):
            return self._error(400, "Invalid UTF-8 CSV")
        result = cleaned.cleaned_csv.encode("utf-8")
        self._send(200, result, "text/csv; charset=utf-8", extra={
            "Content-Disposition": 'attachment; filename="nova-cleaned-review.csv"',
            "X-Nova-Input-Rows": str(cleaned.input_rows),
            "X-Nova-Output-Rows": str(cleaned.output_rows),
            "X-Nova-Owner-Review-Required": "true",
            "X-Nova-Delivery-Status": "owner-review-only-not-delivered",
        })

    def do_PUT(self):
        self._error(503, "Customer routes disabled")

    def do_DELETE(self):
        self._error(503, "Customer routes disabled")


def serve() -> None:
    _validate_runtime()
    port = int(os.environ.get("PORT", "10000"))
    if not 1 <= port <= 65535:
        raise RuntimeError("Invalid port")
    ThreadingHTTPServer(("0.0.0.0", port), PilotHandler).serve_forever()


if __name__ == "__main__":
    serve()
