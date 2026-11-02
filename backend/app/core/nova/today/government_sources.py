"""Bounded, credential-free retrieval of public government source paragraphs."""
from __future__ import annotations

import io
import ipaddress
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, wait
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests

MAX_BYTES = 1_000_000
MAX_DOCUMENTS = 6
MAX_TEXT = 24_000


class SourceUnavailable(ValueError):
    pass


def official_url(value: str, domains: list[str]) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        raise SourceUnavailable("invalid_port")
    if (parsed.scheme != "https" or not host.endswith(".gov") or parsed.username or parsed.password
            or port not in (None, 443) or (domains and not any(host == d or host.endswith("." + d) for d in domains))):
        raise SourceUnavailable("not_allowed_official_url")
    # An archived edition cannot establish a current rule. Current adopted agency
    # deviations and current PDFs remain eligible; dates alone do not mean archive.
    path = unquote(parsed.path).casefold()
    if re.search(r"(?:^|/)(?:archives?|historical)(?:/|$)", path):
        raise SourceUnavailable("archived_source")
    return urlunparse(parsed._replace(fragment=""))


def _public_host(host: str) -> None:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise SourceUnavailable("non_public_address")


class _Text(HTMLParser):
    """Keep block boundaries; exclude executable content and navigation."""
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "template", "svg"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "br", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.title_depth = 0
        self.title = []
        self.body = []
        self.main = []
        self.main_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            if tag in self.SKIP:
                self.hidden.append(tag)
            return
        if tag in self.SKIP:
            self.hidden.append(tag)
            return
        if tag == "title":
            self.title_depth += 1
        if tag == "main":
            self.main_depth += 1
        if tag in self.BLOCK:
            self.handle_data("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag == "title":
            self.title_depth = max(0, self.title_depth - 1)
        if tag in self.BLOCK:
            self.handle_data("\n")
        if tag == "main":
            self.main_depth = max(0, self.main_depth - 1)

    def handle_data(self, data):
        if self.hidden:
            return
        if self.title_depth:
            self.title.append(data)
        else:
            if data != "\n":
                data = re.sub(r"\s+", " ", data)
            self.body.append(data)
            if self.main_depth:
                self.main.append(data)


def _paragraphs(text: str) -> list[str]:
    rows, size = [], 0
    for line in text.splitlines():
        paragraph = re.sub(r"\s+", " ", line).strip()
        if not paragraph:
            continue
        # Never silently chop a provision mid-sentence to satisfy the budget.
        if size + len(paragraph) > MAX_TEXT:
            break
        rows.append(paragraph)
        size += len(paragraph)
    return rows


def fetch_document(url: str, domains: list[str], deadline: float) -> dict:
    current = official_url(url, domains)
    with requests.Session() as session:
        session.trust_env = False  # No ambient proxies, netrc or credentials.
        for redirect in range(3):
            if time.monotonic() >= deadline:
                raise SourceUnavailable("fetch_budget_exhausted")
            _public_host(urlparse(current).hostname)
            remaining = max(0.1, deadline - time.monotonic())
            session.cookies.clear()
            with session.get(current, allow_redirects=False, stream=True,
                             timeout=(min(2.0, remaining), min(3.0, remaining)),
                             headers={"User-Agent": "AMICOR-Nova-SourceReader/1.0", "Accept": "text/html,application/pdf,text/plain"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect == 2:
                        raise SourceUnavailable("too_many_redirects")
                    current = official_url(urljoin(current, response.headers.get("Location", "")), domains)
                    continue
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_content(16384):
                    if len(data) + len(chunk) > MAX_BYTES or time.monotonic() >= deadline:
                        raise SourceUnavailable("source_budget_exhausted")
                    data.extend(chunk)
                kind = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if kind == "application/pdf":
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(data))
                    if reader.is_encrypted or len(reader.pages) > 20:
                        raise SourceUnavailable("pdf_budget_exhausted")
                    text = "\n".join(page.extract_text() or "" for page in reader.pages)
                    title = str((reader.metadata or {}).get("/Title") or urlparse(current).path.rsplit("/", 1)[-1])
                elif kind in {"text/html", "application/xhtml+xml"}:
                    parser = _Text()
                    parser.feed(bytes(data).decode(response.encoding or "utf-8", errors="replace"))
                    text = "".join(parser.main or parser.body)
                    title = " ".join(" ".join(parser.title).split())
                elif kind == "text/plain":
                    text, title = bytes(data).decode("utf-8", errors="replace"), urlparse(current).path
                else:
                    raise SourceUnavailable("unsupported_source_type")
                if re.search(r"\b(?:archived content|this page (?:is|has been) archived|historical version)\b", title + " " + text[:1200], re.I):
                    raise SourceUnavailable("archived_source")
                if time.monotonic() >= deadline:
                    raise SourceUnavailable("source_budget_exhausted")
                paragraphs = _paragraphs(text)
                if not paragraphs or sum(map(len, paragraphs)) < 80:
                    raise SourceUnavailable("source_text_missing")
                return {"url": current, "title": title[:240] or urlparse(current).hostname,
                        "paragraphs": paragraphs}
    raise SourceUnavailable("source_text_missing")


def retrieve_documents(sources: list[dict], domains: list[str], deadline: float) -> tuple[list[dict], int]:
    candidates = []
    for source in sources:
        try:
            url = official_url(source["url"], domains)
        except (SourceUnavailable, KeyError, ValueError):
            continue
        if url not in candidates:
            candidates.append(url)
    candidates = candidates[:MAX_DOCUMENTS]
    pool = ThreadPoolExecutor(max_workers=MAX_DOCUMENTS)
    futures = [pool.submit(fetch_document, url, domains, deadline) for url in candidates]
    done, pending = wait(futures, timeout=max(0, deadline - time.monotonic()))
    documents = []
    for future in futures:  # Stable source order despite concurrent retrieval.
        if future in done:
            try:
                documents.append(future.result())
            except Exception:
                pass  # Report a source gap, never substitute search snippets.
        else:
            future.cancel()
    pool.shutdown(wait=False, cancel_futures=True)
    return documents, len(sources) - len(documents)
