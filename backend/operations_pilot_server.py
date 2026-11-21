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

OWNER_UI = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nova Operations | Supervised CSV Pilot</title>
<style>body{font:16px system-ui,sans-serif;background:#f6f8fb;color:#142238;margin:0}
main{max-width:660px;margin:40px auto;padding:28px;background:white;border-radius:16px;box-shadow:0 4px 22px #20304014}
h1{font-size:1.5rem;margin:0 0 8px}p{line-height:1.5;color:#49596d}
label{display:block;margin:18px 0 6px;font-weight:650}input{width:100%;box-sizing:border-box;padding:11px;border:1px solid #a5b1be;border-radius:8px}
button{margin-top:20px;padding:12px 18px;border:0;border-radius:8px;background:#123e74;color:#fff;font-weight:700;cursor:pointer}
button:disabled{opacity:.55}#message{white-space:pre-wrap;margin-top:18px}a{color:#123e74}
small{color:#5d6977}</style></head><body><main>
<h1>Nova Operations — supervised CSV pilot</h1>
<p><strong>Synthetic staging data only.</strong> This screen is not a live customer upload portal. CSVs are not saved by this pilot; output requires your review before any delivery.</p>
<label for="token">Owner pilot access token</label><input id="token" type="password" autocomplete="off" placeholder="Staging owner token">
<label for="csv">Synthetic CSV file (up to 1 MB)</label><input id="csv" type="file" accept=".csv,text/csv">
<button id="run" type="button">Clean synthetic CSV for review</button>
<p id="message" role="status" aria-live="polite"></p><a id="download" hidden>Download review-only CSV</a>
<p><small>No files or access tokens are stored in the browser by this page. Customer processing and automatic delivery remain disabled.</small></p>
</main><script>
const run=document.getElementById('run'),msg=document.getElementById('message'),link=document.getElementById('download');
let prior=null;
run.addEventListener('click',async()=>{
 const token=document.getElementById('token').value;
 const file=document.getElementById('csv').files[0];
 if(prior){URL.revokeObjectURL(prior);prior=null;}
 link.hidden=true;msg.textContent='';
 if(!token||!file){msg.textContent='Owner token and synthetic CSV required.';return;}
 if(file.size<1||file.size>1000000){msg.textContent='CSV must be 1 to 1,000,000 bytes.';return;}
 run.disabled=true;msg.textContent='Processing synthetic CSV...';
 try{
  const res=await fetch('/operations/pilot/csv-clean',{method:'POST',headers:{
   'Authorization':'Bearer '+token,'X-Nova-Owner-Action':'process-csv-for-owner-review',
   'X-Nova-Synthetic-Data':'true','Content-Type':'text/csv'},body:file});
  if(!res.ok){msg.textContent='Request blocked ('+res.status+'). Check staging authorization and CSV format.';return;}
  const output=await res.blob();
  prior=URL.createObjectURL(output);
  link.href=prior;link.download='nova-cleaned-review.csv';link.hidden=false;
  msg.textContent='Review candidate ready. Input rows: '+(res.headers.get('X-Nova-Input-Rows')||'?')+
   '. Output rows: '+(res.headers.get('X-Nova-Output-Rows')||'?')+'. Not delivered to any customer.';
 }catch(_){msg.textContent='Could not connect to the pilot endpoint.'}
 finally{run.disabled=false}
});
</script></body></html>"""


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
        if path == "/pilot":
            return self._send(200, OWNER_UI.encode("utf-8"), "text/html; charset=utf-8")
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
