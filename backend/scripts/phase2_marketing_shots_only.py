"""Capture Phase 2 approval screenshots via Playwright + TestClient ASGI proxy."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.main import app  # noqa: E402

OUT_DIR = ROOT / "backend" / "static" / "marketing" / "phase2-screenshots"
ORIGIN = "http://marketing.local"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    console_errors: list[str] = []

    def fulfill(route):
        req = route.request
        parsed = urlparse(req.url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        method = req.method.upper()
        headers = {k: v for k, v in req.headers.items() if k.lower() != "host"}
        body = req.post_data
        try:
            response = client.request(method, path, headers=headers, content=body)
        except Exception as exc:
            route.fulfill(status=500, body=str(exc))
            return
        content_type = response.headers.get("content-type", "application/octet-stream")
        route.fulfill(
            status=response.status_code,
            headers={"content-type": content_type},
            body=response.content,
        )

    targets = [
        ("provider-desktop", "/for-providers", 1440, 900, False),
        ("provider-mobile", "/for-providers", 390, 844, False),
        ("driver-desktop", "/for-drivers", 1440, 900, False),
        ("driver-mobile", "/for-drivers", 390, 844, False),
        ("home-trust", "/", 1440, 900, True),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for slug, path, width, height, scroll_trust in targets:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.route("**/*", fulfill)
            page.on(
                "console",
                lambda msg, slug=slug: console_errors.append(f"{slug}: {msg.text}")
                if msg.type == "error"
                else None,
            )
            page.goto(f"{ORIGIN}{path}", wait_until="load", timeout=60000)
            if scroll_trust:
                page.locator("#trust-heading").scroll_into_view_if_needed()
                time.sleep(0.35)
            out = OUT_DIR / f"{slug}.png"
            page.screenshot(path=str(out), full_page=True)
            print("wrote", out)
            page.close()
        browser.close()

    if console_errors:
        print("CONSOLE_ERRORS")
        for item in console_errors:
            print(item)
        return 1
    print("SCREENSHOTS_OK", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
