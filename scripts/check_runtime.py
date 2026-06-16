#!/usr/bin/env python3
"""Runtime verification checks for Phase 33B orchestration stabilization.

This script is intentionally read-only and never starts/stops uvicorn.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpResult:
    status: int | None
    content_type: str
    body: str
    location: str
    error: str | None


def env_host_port() -> tuple[str, int]:
    host = os.getenv("AMICOR_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.getenv("AMICOR_PORT", "8011")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError(f"AMICOR_PORT must be an integer, got: {port_raw}") from exc
    if port <= 0 or port > 65535:
        raise ValueError(f"AMICOR_PORT must be in range 1-65535, got: {port}")
    return host, port


def fetch(url: str, timeout: float = 8.0) -> HttpResult:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return HttpResult(
                status=int(response.getcode()),
                content_type=response.headers.get("Content-Type", ""),
                body=body,
                location=response.headers.get("Location", ""),
                error=None,
            )
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return HttpResult(
            status=int(exc.code),
            content_type=exc.headers.get("Content-Type", "") if exc.headers else "",
            body=body,
            location=exc.headers.get("Location", "") if exc.headers else "",
            error=None,
        )
    except URLError as exc:
        return HttpResult(None, "", "", "", f"urlerror: {exc.reason}")
    except TimeoutError:
        return HttpResult(None, "", "", "", "timeout")


def fetch_no_redirect(url: str, timeout: float = 8.0) -> HttpResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return HttpResult(None, "", "", "", f"unsupported scheme: {parsed.scheme}")

    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    host = parsed.hostname or ""
    port = parsed.port
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    conn = connection_cls(host, port=port, timeout=timeout)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read().decode("utf-8", errors="replace")
        return HttpResult(
            status=int(response.status),
            content_type=response.getheader("Content-Type", "") or "",
            body=body,
            location=response.getheader("Location", "") or "",
            error=None,
        )
    except (OSError, http.client.HTTPException) as exc:
        return HttpResult(None, "", "", "", str(exc))
    finally:
        conn.close()


def is_json_content(result: HttpResult) -> bool:
    ctype = result.content_type.lower()
    return "application/json" in ctype or result.body.lstrip().startswith("{")


def is_html_content(result: HttpResult) -> bool:
    ctype = result.content_type.lower()
    head = result.body.lstrip().lower()
    return "text/html" in ctype or head.startswith("<!doctype") or head.startswith("<html")


def check(name: str, ok: bool, details: str) -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"{name}={status} :: {details}")
    return ok


def main() -> int:
    try:
        host, port = env_host_port()
    except ValueError as exc:
        print(f"CONFIG=FAIL :: {exc}")
        return 2

    base = f"http://{host}:{port}"
    print(json.dumps({"runtime_base": base}, separators=(",", ":")))

    preflight = fetch(f"{base}/api/health")
    if preflight.status != 200:
        print(
            "ATTACHMENT_MODE=FAIL :: canonical runtime not reachable; start it with scripts/dev_up.ps1"
        )
        print(f"OVERALL=FAIL")
        return 1

    checks: list[bool] = []

    health = fetch(f"{base}/api/health")
    checks.append(
        check(
            "API_HEALTH_JSON_200",
            health.status == 200 and is_json_content(health) and not is_html_content(health),
            f"status={health.status};ctype={health.content_type};error={health.error}",
        )
    )

    app_shell = fetch(f"{base}/app")
    checks.append(
        check(
            "APP_SHELL_HTML_200",
            app_shell.status == 200 and is_html_content(app_shell),
            f"status={app_shell.status};ctype={app_shell.content_type};error={app_shell.error}",
        )
    )

    governance_shell = fetch(f"{base}/app/operations/governance")
    checks.append(
        check(
            "GOVERNANCE_SHELL_HTML_200",
            governance_shell.status == 200 and is_html_content(governance_shell),
            f"status={governance_shell.status};ctype={governance_shell.content_type};error={governance_shell.error}",
        )
    )

    legacy_redirect = fetch_no_redirect(f"{base}/operations/governance")
    checks.append(
        check(
            "LEGACY_GOVERNANCE_REDIRECT",
            legacy_redirect.status in {307, 308}
            and legacy_redirect.location.endswith("/app/operations/governance"),
            f"status={legacy_redirect.status};location={legacy_redirect.location};error={legacy_redirect.error}",
        )
    )

    missing_api = fetch(f"{base}/api/canonical-runtime-does-not-exist")
    checks.append(
        check(
            "INVALID_API_JSON_404",
            missing_api.status == 404 and is_json_content(missing_api) and not is_html_content(missing_api),
            f"status={missing_api.status};ctype={missing_api.content_type};error={missing_api.error}",
        )
    )

    missing_asset = fetch(f"{base}/assets/canonical-runtime-does-not-exist.js")
    checks.append(
        check(
            "INVALID_ASSET_404",
            missing_asset.status == 404 and not is_html_content(missing_asset),
            f"status={missing_asset.status};ctype={missing_asset.content_type};error={missing_asset.error}",
        )
    )

    # Verifies runtime still responds at end of validation execution.
    post_health = fetch(f"{base}/api/health")
    checks.append(
        check(
            "RUNTIME_ALIVE_POST_VALIDATION",
            post_health.status == 200 and is_json_content(post_health),
            f"status={post_health.status};ctype={post_health.content_type};error={post_health.error}",
        )
    )

    overall_ok = all(checks)
    print(f"OVERALL={'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
