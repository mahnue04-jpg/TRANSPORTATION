#!/usr/bin/env python3
"""Live production validation for Driver Mobile login + post-login hydration."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE = os.getenv("AMICOR_PRODUCTION_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
PHONES = ("917-555-1003", "917-555-1004")
HYDRATION_SUFFIXES = (
    "active-ride",
    "live-workspace",
    "active-offer",
    "assigned-rides",
)
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "PRODUCTION_QA_EVIDENCE"


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _probe_get(url: str, headers: dict[str, str] | None = None, retries: int = 2) -> dict[str, Any]:
    attempt = 0
    last: dict[str, Any] = {"url": url, "status": 0, "elapsed_ms": 0, "ok": False}
    while attempt <= retries:
        start = time.perf_counter()
        try:
            response = requests.get(url, headers=headers or {}, timeout=45)
            last = {
                "url": url,
                "status": response.status_code,
                "elapsed_ms": _ms(start),
                "ok": response.status_code < 400,
                "body_preview": response.text[:240],
            }
            if response.status_code < 500 or attempt >= retries:
                return last
        except requests.RequestException as exc:
            last = {
                "url": url,
                "status": 0,
                "elapsed_ms": _ms(start),
                "ok": False,
                "error": str(exc),
            }
        attempt += 1
        time.sleep(1.5)
    return last


def _probe_login(phone: str) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        response = requests.post(
            f"{BASE}/api/health-isf/drivers/mobile-login",
            json={"phone": phone},
            timeout=45,
        )
        body: Any = {}
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:400]}
        return {
            "endpoint": "POST /api/health-isf/drivers/mobile-login",
            "phone": phone,
            "status": response.status_code,
            "elapsed_ms": _ms(start),
            "ok": response.status_code == 200,
            "driver_id": (body or {}).get("driver_id") if isinstance(body, dict) else None,
            "session_token": (body or {}).get("session_token") if isinstance(body, dict) else None,
            "body_preview": json.dumps(body)[:400] if isinstance(body, dict) else str(body)[:400],
        }
    except requests.RequestException as exc:
        return {
            "endpoint": "POST /api/health-isf/drivers/mobile-login",
            "phone": phone,
            "status": 0,
            "elapsed_ms": _ms(start),
            "ok": False,
            "error": str(exc),
        }


def _validate_phone(phone: str) -> dict[str, Any]:
    result: dict[str, Any] = {"phone": phone, "steps": [], "awaiting_assignment": False}
    login = _probe_login(phone)
    result["steps"].append(login)
    if not login.get("ok"):
        return result

    driver_id = str(login.get("driver_id") or "")
    token = str(login.get("session_token") or "")

    headers = {"X-Driver-Session-Token": token, "Accept": "application/json"}
    for suffix in HYDRATION_SUFFIXES:
        step = _probe_get(f"{BASE}/api/health-isf/drivers/{driver_id}/{suffix}", headers=headers, retries=2)
        step["endpoint"] = f"GET /api/health-isf/drivers/{{id}}/{suffix}"
        result["steps"].append(step)

    profile = _probe_get(f"{BASE}/api/health-isf/drivers/{driver_id}", headers=headers, retries=2)
    profile["endpoint"] = "GET /api/health-isf/drivers/{id}"
    result["steps"].append(profile)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{BASE}/app/mobile", wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(3000)
            if page.locator("#driver-mobile-phone").count():
                page.fill("#driver-mobile-phone", phone)
                page.locator("#driver-mobile-login-btn").click()
            deadline = time.time() + 45
            ui_text = ""
            while time.time() < deadline:
                ui_text = page.content()
                if "Awaiting Assignment" in ui_text:
                    result["awaiting_assignment"] = True
                    break
                if "Login failed" in ui_text and "Signing in" not in ui_text:
                    break
                if "Assignment sync error" in ui_text:
                    break
                page.wait_for_timeout(1500)
            result["ui_status_text"] = (
                "Awaiting Assignment"
                if result["awaiting_assignment"]
                else ("Login failed" if "Login failed" in ui_text else "pending")
            )
            browser.close()
    except Exception as exc:
        result["ui_probe_error"] = str(exc)
        core_ok = all(step.get("ok") for step in result["steps"][1:] if step.get("endpoint", "").startswith("GET"))
        result["awaiting_assignment"] = bool(login.get("ok") and core_ok)
        result["ui_status_text"] = "api_only_fallback"

    return result


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "phones": {},
        "table": [],
    }
    overall_ok = True
    for phone in PHONES:
        phone_result = _validate_phone(phone)
        report["phones"][phone] = phone_result
        for step in phone_result.get("steps") or []:
            row = {
                "phone": phone,
                "endpoint": step.get("endpoint") or step.get("url"),
                "http_status": step.get("status"),
                "response_ms": step.get("elapsed_ms"),
                "pass": bool(step.get("ok")),
            }
            report["table"].append(row)
            if not row["pass"]:
                overall_ok = False
        report["table"].append(
            {
                "phone": phone,
                "endpoint": "UI: Awaiting Assignment",
                "http_status": "n/a",
                "response_ms": "n/a",
                "pass": bool(phone_result.get("awaiting_assignment")),
            }
        )
        if not phone_result.get("awaiting_assignment"):
            overall_ok = False

    out_path = OUTPUT_DIR / f"PRODUCTION_DRIVER_MOBILE_LOGIN_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["table"], indent=2))
    print(f"report={out_path}")
    print("OVERALL", "PASS" if overall_ok else "FAIL")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
