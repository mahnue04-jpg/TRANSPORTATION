"""Bounded, read-only review of owner-selected public prospect websites.

This is a development execution path, not independent web-search discovery,
customer delivery, outreach, or proof that a business wants to buy a product.
Source content is data and never instructions. No LLM or paid API is used.
"""
from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .operations_csv_cleanup import clean_csv_text

MAX_BYTES = 1_000_000
SIGNALS = {
    "consultation": r"\bconsultation\b",
    "custom_quote": r"\b(?:custom|personalized|personalised).{0,45}(?:quote|trip|travel|tour|vacation|itinerary)\b",
    "group_travel": r"\bgroup (?:travel|trip|tour)",
    "inquiry": r"\b(?:inquiry|enquiry|inquiries|enquiries)\b",
    "whatsapp": r"\bwhatsapp\b",
}


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.depth = 0; self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}: self.depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}: self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if not self.depth and data.strip(): self.parts.append(data.strip())


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # A new destination requires a separately reviewed source URL.


def validate_source(url, allowed_hosts):
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or p.username or p.password or p.port not in {None,443}:
        raise ValueError("Only public HTTPS source URLs are supported")
    if host not in allowed_hosts or not host or host.endswith(".local"):
        raise ValueError("Source host is outside this assignment")
    try:
        addresses = [a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    except socket.gaierror:
        # Proxied development environments may not expose a local DNS resolver.
        # Resolve the exact assignment host over HTTPS; never skip address checks.
        query = urlencode({'name':host,'type':'A'})
        with build_opener(NoRedirect()).open('https://dns.google/resolve?'+query,timeout=10) as response:
            payload = json.loads(response.read(64000))
        if payload.get('Status') != 0: raise ValueError('Public DNS lookup failed')
        addresses = [a['data'] for a in payload.get('Answer',[]) if a.get('type')==1]
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Non-public source address blocked")
    return host


def fetch_source(url, allowed_hosts):
    validate_source(url, allowed_hosts)
    req = Request(url, headers={"User-Agent":"AMICOR-Nova-Research/0.1 (read-only owner review)"})
    with build_opener(NoRedirect()).open(req, timeout=15) as response:
        if response.headers.get_content_type() not in {"text/html", "text/plain"}:
            raise ValueError("Unsupported source content type")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES: raise ValueError("Source exceeds size limit")
        charset = response.headers.get_content_charset() or "utf-8"
        return raw, raw.decode(charset, errors="replace")


def assess_source(name, url, raw, html):
    parser = VisibleText(); parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts))
    evidence = []
    for label, pattern in SIGNALS.items():
        m = re.search(pattern, text, re.I)
        if m:
            start = max(0, text.rfind(". ", 0, m.start()) + 2)
            evidence.append({"signal": label, "excerpt":text[max(start,m.start()-65):m.end()+100][:210]})
    return {"business":name,"source_url":url,"domain":urlsplit(url).hostname.removeprefix("www."),
            "source_sha256":hashlib.sha256(raw).hexdigest(),
            "checked_at":datetime.now(timezone.utc).isoformat(),
            "evidence":evidence,"status":"WORKFLOW_FIT_REQUIRES_QUALIFICATION" if evidence else "INSUFFICIENT_EVIDENCE",
            "buying_interest":"UNVERIFIED","introduction_consent":"NOT_OBTAINED",
            "next_action":"Owner review, then qualify need, volume, buyer, budget and timing after launch approval"}


def _private_write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd,"wb") as f: f.write(raw); f.flush(); os.fsync(f.fileno())


def run_assignment(seeds, output_dir):
    if not 1 <= len(seeds) <= 25: raise ValueError("Assignment requires 1–25 sources")
    root = Path(output_dir); root.mkdir(parents=True, mode=0o700, exist_ok=False)
    allowed = {(urlsplit(s["url"]).hostname or "").lower() for s in seeds}
    rows, failures, seen = [], [], set()
    for seed in seeds:
        domain = (urlsplit(seed["url"]).hostname or "").removeprefix("www.").lower()
        if domain in seen: continue
        seen.add(domain)
        try:
            raw, html = fetch_source(seed["url"], allowed)
            row = assess_source(seed["name"],seed["url"],raw,html)
            row["record_id"]="BTR-"+hashlib.sha256(domain.encode()).hexdigest()[:12]
            _private_write(root/(row["record_id"]+".source.html"),raw)
            rows.append(row)
        except Exception as exc:
            failures.append({"business":seed["name"],"url":seed["url"],"error_type":type(exc).__name__})
    rows.sort(key=lambda r: (-len(r["evidence"]),r["domain"]))
    out=io.StringIO(); fields=["record_id","business","domain","source_url","checked_at","status","buying_interest","introduction_consent","workflow_signals","evidence","next_action"]
    writer=csv.DictWriter(out,fieldnames=fields,lineterminator="\n");writer.writeheader()
    for row in rows:
        writer.writerow({**{k:row[k] for k in fields if k not in {"workflow_signals","evidence"}},"workflow_signals":", ".join(e["signal"] for e in row["evidence"]),"evidence":" | ".join(e["excerpt"] for e in row["evidence"])})
    cleanup=clean_csv_text(out.getvalue())
    _private_write(root/"operations-review.csv",cleanup.cleaned_csv.encode())
    manifest={"schema_version":1,"execution":"LOCAL_DEVELOPMENT_PRODUCT_CODE","input":"OWNER_SELECTED_PUBLIC_SOURCE_URLS","independent_business_discovery":False,"owner_review":"PENDING","outreach_sent":0,"source_count":len(rows),"failures":failures,"records":rows,"operations":{"processor":"operations_csv_cleanup.clean_csv_text","output_rows":cleanup.output_rows,"duplicates_removed":cleanup.duplicate_rows_removed,"output_sha256":cleanup.output_sha256}}
    _private_write(root/"manifest.json",json.dumps(manifest,indent=2).encode())
    return manifest


def verify_saved_run(root):
    root=Path(root);m=json.loads((root/"manifest.json").read_text())
    if hashlib.sha256((root/"operations-review.csv").read_bytes()).hexdigest()!=m["operations"]["output_sha256"]:
        raise ValueError("Output integrity check failed")
    for r in m["records"]:
        if hashlib.sha256((root/(r["record_id"]+".source.html")).read_bytes()).hexdigest()!=r["source_sha256"]:
            raise ValueError("Source integrity check failed")
    return {"source_count":m["source_count"],"output_rows":m["operations"]["output_rows"],"owner_review":m["owner_review"],"outreach_sent":m["outreach_sent"],"integrity_verified":True}
