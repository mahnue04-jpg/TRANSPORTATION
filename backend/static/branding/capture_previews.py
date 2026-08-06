"""Capture branded UI previews for deployment review (no API/auth changes)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright not installed; run: pip install playwright && playwright install chromium")
    sys.exit(1)

BASE = os.environ.get("AMICOR_PREVIEW_BASE", "http://127.0.0.1:8000")
OUT = Path(__file__).resolve().parent / "preview-screenshots"
OUT.mkdir(parents=True, exist_ok=True)

SCREENS = [
    ("01-landing", "/", {"width": 1440, "height": 900}),
    ("02-login", "/workspace?amicor_preview=login", {"width": 1440, "height": 900}),
    ("03-dispatch-dashboard", "/app/dispatch", {"width": 1440, "height": 900}),
    ("04-rider-app", "/app/riders", {"width": 390, "height": 844}),
    ("05-driver-mobile", "/app/mobile", {"width": 390, "height": 844}),
    ("06-provider-portal", "/app/providers", {"width": 1440, "height": 900}),
    ("07-ai-assistant", "/app/ai-assistant", {"width": 1440, "height": 900}),
    ("08-admin-dashboard", "/admin", {"width": 1440, "height": 900}),
    ("09-driver-apply", "/platform-ops/driver-apply", {"width": 1440, "height": 900}),
    ("10-ops-dashboard", "/app/dashboard", {"width": 1440, "height": 900}),
]


def set_role(page, role: str) -> None:
    page.evaluate(
        """(role) => {
          localStorage.setItem('amicor_platform_role', role);
          localStorage.setItem('amicor_shell_role', role);
        }""",
        role,
    )


def capture() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for slug, path, viewport in SCREENS:
            page = browser.new_page(viewport=viewport)
            url = BASE.rstrip("/") + path
            try:
                if slug in {"04-rider-app", "05-driver-mobile"}:
                    page.set_viewport_size({"width": 1440, "height": 900})
                    page.goto(BASE.rstrip("/") + "/app/dashboard", wait_until="networkidle", timeout=60000)
                    set_role(page, "rider" if slug == "04-rider-app" else "driver")
                    page.set_viewport_size(viewport)
                if slug == "06-provider-portal":
                    page.goto(BASE.rstrip("/") + "/app/dashboard", wait_until="networkidle", timeout=60000)
                    set_role(page, "provider")
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)
                if slug == "02-login":
                    page.evaluate(
                        """() => {
                          if (window.AmiCorAuthUI && typeof window.AmiCorAuthUI.showLogin === 'function') {
                            window.AmiCorAuthUI.showLogin();
                          }
                        }"""
                    )
                    page.wait_for_timeout(800)
                out = OUT / f"{slug}.png"
                page.screenshot(path=str(out), full_page=True)
                print(f"saved {out}")
            except Exception as exc:
                print(f"WARN {slug}: {exc}")
            finally:
                page.close()
        browser.close()


if __name__ == "__main__":
    for _ in range(30):
        import urllib.request

        try:
            urllib.request.urlopen(BASE, timeout=2)
            break
        except Exception:
            time.sleep(1)
    else:
        print(f"Server not reachable at {BASE}")
        sys.exit(1)
    capture()
    print(f"Preview screenshots in {OUT}")
