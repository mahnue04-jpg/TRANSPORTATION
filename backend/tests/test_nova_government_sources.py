"""Offline source retrieval boundaries, including observed archived-FAR failure."""
import socket
import time
from types import SimpleNamespace

import pytest
import requests

from app.core.nova.today import government_sources as sources


@pytest.mark.parametrize("url", [
    "https://www.acquisition.gov/sites/default/files/archives/far/pdf/2025-01.pdf",
    "https://www.acquisition.gov/%61rchives/rule.pdf",
    "https://sam.gov/historical/registration", "http://sam.gov/entity-registration",
    "https://sam.gov.attacker.example/", "https://sam.gov:8443/", "https://u:p@sam.gov/",
    "https://sam.gov:abc/", "https://mn.gov/",
])
def test_unapproved_urls_and_archived_editions_are_rejected(url):
    with pytest.raises(sources.SourceUnavailable):
        sources.official_url(url, ["acquisition.gov", "sam.gov"])


@pytest.mark.parametrize("url", [
    "https://www.acquisition.gov/far/32.501-1",
    "https://www.acquisition.gov/far-overhaul/agency-deviations",
    "https://www.acquisition.gov/sites/default/files/2026-09/adopted-deviation.pdf",
    "https://sam.gov/sites/default/files/2024-11/entity-checklist.pdf",
])
def test_current_sources_and_adopted_deviations_are_not_rejected_for_being_pdfs_or_dated(url):
    assert sources.official_url(url, ["acquisition.gov", "sam.gov"]) == url


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "192.168.1.1"])
def test_nonpublic_dns_is_rejected(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, (ip, 443))])
    with pytest.raises(sources.SourceUnavailable, match="non_public_address"):
        sources._public_host("sam.gov")


def install_session(monkeypatch, responses):
    calls = []
    class Response:
        def __init__(self, status=200, data=b"", kind="text/html", location=""):
            self.status_code, self.data, self.encoding = status, data, "utf-8"
            self.headers = {"Content-Type": kind, "Location": location}
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self):
            if self.status_code >= 400: raise requests.HTTPError("fixture")
        def iter_content(self, n): yield self.data
    class Session:
        trust_env = True
        cookies = SimpleNamespace(clear=lambda: None)
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url, **kw):
            calls.append((url, kw, self.trust_env))
            return Response(**responses[len(calls) - 1])
    monkeypatch.setattr(sources.requests, "Session", Session)
    monkeypatch.setattr(sources, "_public_host", lambda host: None)
    return calls


BODY = b'''<html><title>Progress payment scope</title><nav>Navigation not evidence</nav>
<main><h1>Cost-based progress payments</h1><p>The customary rate is 80 percent,
except for small business concerns. This is a synthetic retrieval fixture.</p>
<p>Scope applies to this method only.</p><script>malicious script</script></main></html>'''


def test_html_body_and_title_are_source_owned_and_preserve_context(monkeypatch):
    calls = install_session(monkeypatch, [{"data": BODY}])
    result = sources.fetch_document("https://www.acquisition.gov/far/32.501-1", ["acquisition.gov"], time.monotonic() + 5)
    assert result["title"] == "Progress payment scope"
    assert result["paragraphs"] == ["Cost-based progress payments", "The customary rate is 80 percent, except for small business concerns. This is a synthetic retrieval fixture.", "Scope applies to this method only."]
    assert not calls[0][1]["allow_redirects"] and calls[0][2] is False
    assert calls[0][1]["stream"] is True


@pytest.mark.parametrize("target", ["https://commercial.example/", "https://mn.gov/", "/archives/far/2025.pdf", "http://sam.gov/"])
def test_redirect_is_validated_before_any_request_to_target(monkeypatch, target):
    calls = install_session(monkeypatch, [{"status": 302, "location": target}])
    with pytest.raises(sources.SourceUnavailable):
        sources.fetch_document("https://sam.gov/source", ["sam.gov"], time.monotonic() + 5)
    assert len(calls) == 1


def test_allowed_redirect_rechecks_host_and_retains_final_source_url(monkeypatch):
    calls = install_session(monkeypatch, [{"status": 302, "location": "/current"}, {"data": BODY}])
    hosts = []
    monkeypatch.setattr(sources, "_public_host", hosts.append)
    result = sources.fetch_document("https://sam.gov/start", ["sam.gov"], time.monotonic() + 5)
    assert len(calls) == 2 and hosts == ["sam.gov", "sam.gov"]
    assert result["url"] == "https://sam.gov/current"


@pytest.mark.parametrize("response", [
    {"data": b"x" * (sources.MAX_BYTES + 1)},
    {"data": b"not evidence", "kind": "application/octet-stream"},
    {"data": b"<title>Archived content</title><main>" + BODY + b"</main>"},
    {"data": b"<main>Sign in</main>"}, {"status": 403},
])
def test_unreadable_oversized_and_archived_bodies_are_not_evidence(monkeypatch, response):
    install_session(monkeypatch, [response])
    with pytest.raises((sources.SourceUnavailable, requests.HTTPError)):
        sources.fetch_document("https://sam.gov/source", [], time.monotonic() + 5)


def test_partial_fetch_keeps_readable_documents_but_does_not_use_search_snippets(monkeypatch):
    calls = []
    def fetch(url, domains, deadline):
        calls.append(url)
        if url.endswith("/broken"): raise requests.Timeout()
        return {"url": url, "title": "Fixture", "paragraphs": ["Actual body fixture"]}
    monkeypatch.setattr(sources, "fetch_document", fetch)
    rows = [{"url": "https://sam.gov/current", "title": "Untrusted search title", "snippet": "Unchecked snippet"},
            {"url": "https://sam.gov/broken"}, {"url": "https://sam.gov/archives/old"}]
    docs, gaps = sources.retrieve_documents(rows, ["sam.gov"], time.monotonic() + 1)
    assert len(docs) == 1 and gaps == 2
    assert docs[0]["paragraphs"] == ["Actual body fixture"]
    assert "https://sam.gov/archives/old" not in calls


def test_plain_text_extraction_does_not_truncate_a_rule_mid_paragraph(monkeypatch):
    monkeypatch.setattr(sources, "MAX_TEXT", 10)
    assert sources._paragraphs("small\nA rule longer than remaining space") == ["small"]


def test_substantive_program_panels_outside_main_are_retained(monkeypatch):
    html = (b"<title>Official program fixture</title><main><h1>Certifications</h1>"
            b"<p>Introductory program overview.</p></main>"
            b"<section><h2>Program qualifications</h2><p>Detailed eligibility conditions are in this "
            b"synthetic source-owned panel outside the main element.</p></section>")
    install_session(monkeypatch, [{"data": html}])
    result = sources.fetch_document("https://www.sba.gov/certifications/", ["sba.gov"], time.monotonic() + 5)
    assert "Program qualifications" in result["paragraphs"]
    assert any("Detailed eligibility conditions" in paragraph for paragraph in result["paragraphs"])
