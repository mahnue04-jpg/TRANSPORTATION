"""Real Chromium walkthrough for the loopback-only synthetic Operations demo.

Execute only in isolated CI after installing playwright + Chromium.
No production endpoints, network logins, customer data, or Render secrets.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

BASE_PATH = "/api/nova/work/operations/synthetic-acceptance"
EXPECTED = b"Name,Department\nAda,Operations\nMina,Research\n"


def open_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    if os.getenv("DATABASE_URL") or os.getenv("RENDER") or os.getenv("RENDER_SERVICE_NAME"):
        raise RuntimeError("Cannot run synthetic browser test against a deployed/database-connected environment")
    port = open_loopback_port()
    origin = f"http://127.0.0.1:{port}"
    username = "browser-fixture-owner"
    password = secrets.token_urlsafe(32)
    allowed = ("PATH", "HOME", "PYTHONPATH", "VIRTUAL_ENV", "SYSTEMROOT", "PLAYWRIGHT_BROWSERS_PATH")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update({
        "APP_ENV": "demo", "AMICOR_ENVIRONMENT": "demo", "NOVA_DEMO_STANDALONE": "true",
        "NOVA_DEMO_OWNER_USER": username, "NOVA_DEMO_OWNER_PASSWORD": password,
    })
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "scripts.nova_operations_standalone_demo:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Isolated demo server exited before listening")
            try:
                urlopen(origin + BASE_PATH + "/ui", timeout=0.2)
            except HTTPError as exc:
                if exc.code == 401:
                    break  # owner auth is active
            except (OSError, TimeoutError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Local demo server did not become ready")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                http_credentials={"username": username, "password": password},
                accept_downloads=True,
            )
            page = context.new_page()
            page.goto(origin + BASE_PATH + "/ui", wait_until="domcontentloaded")
            assert page.get_by_role("heading", name="Review a synthetic CSV assignment").is_visible()
            page.get_by_role("button", name="Load sample for review").click()
            page.get_by_text("Awaiting your review.").wait_for()
            assert "Ada,Operations" in page.locator("#preview").inner_text()
            assert page.get_by_role("button", name="Download approved CSV").is_disabled()
            page.get_by_label("I inspected this synthetic CSV").check()
            page.get_by_role("button", name="Approve sample").click()
            page.get_by_text("Decision recorded: approved").wait_for()
            with page.expect_download() as info:
                page.get_by_role("button", name="Download approved CSV").click()
            download = info.value
            assert download.suggested_filename == "nova-synthetic-cleaned.csv"
            contents = Path(download.path()).read_bytes()
            assert contents == EXPECTED, (hashlib.sha256(contents).hexdigest(), len(contents))
            assert page.get_by_role("button", name="Reject sample").is_disabled()
            context.close()
            browser.close()
        print("Chromium synthetic owner sign-in, preview, review, and downloaded CSV verified.")
    finally:
        server.terminate()
        try:
            server.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate()


if __name__ == "__main__":
    main()
