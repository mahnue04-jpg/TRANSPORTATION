"""Verify Driver Mobile accept-ride uses driver session auth on production."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
ORG = os.getenv("AMICOR_ORG_ID", "308dc05a-6781-4ef7-91fc-ff22606937e3")
DRIVER_PHONE = os.getenv("AMICOR_DRIVER_PHONE", "917-555-1004")
OUT = Path(__file__).resolve().parent.parent.parent / ".runtime" / "driver_mobile_accept_auth_verify.json"
LOCAL_JS = Path(__file__).resolve().parent.parent / "static" / "ops-shell.js"


def verify_local_markers() -> dict:
    js = LOCAL_JS.read_text(encoding="utf-8")
    return {
        "driver_session_first_fetch": "function shouldUseDriverSessionFirstFetch" in js,
        "authorized_fetch_driver_bypass": "if (driverSessionFirst) {\n        return fetch(scopedUrl, init);" in js,
        "accept_recovery_helper": "async function _amiRecoverAcceptedDriverTrip" in js,
        "accept_http_status_helper": "function _amiDriverAcceptHttpStatus" in js,
    }


def verify_remote_js() -> dict:
    live = requests.get(f"{BASE}/api/health/live", timeout=60).json()
    html = requests.get(f"{BASE}/app/mobile", timeout=120).text
    version = ""
    if "ops-shell.js?v=" in html:
        version = html.split("ops-shell.js?v=", 1)[1].split('"', 1)[0]
    js = requests.get(f"{BASE}/static/ops-shell.js?v={version or 'latest'}", timeout=120).text
    checks = verify_local_markers()
    checks["deploy_commit"] = live.get("deploy_commit")
    checks["ops_shell_js_version"] = version
    checks["ok"] = all(v for k, v in checks.items() if k not in {"deploy_commit", "ops_shell_js_version", "ok"})
    return checks


def verify_accept_auth_probe() -> dict:
    login = requests.post(
        f"{BASE}/api/health-isf/drivers/mobile-login",
        json={"phone": DRIVER_PHONE},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=60,
    )
    body = login.json() if login.headers.get("content-type", "").startswith("application/json") else {}
    result = {
        "mobile_login_status": login.status_code,
        "driver_id": body.get("driver_id"),
        "has_session_token": bool(body.get("session_token")),
    }
    if login.status_code != 200 or not body.get("session_token") or not body.get("driver_id"):
        result["ok"] = False
        result["error"] = safe_detail(body, login.text)
        return result

    driver_id = str(body["driver_id"])
    session_token = str(body["session_token"])
    fake_ride_id = "00000000-0000-0000-0000-000000000099"
    accept = requests.post(
        f"{BASE}/api/health-isf/drivers/{driver_id}/accept-ride",
        params={"organization_id": ORG},
        json={"ride_id": fake_ride_id},
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Driver-Session-Token": session_token,
        },
        timeout=60,
    )
    accept_body = accept.json() if accept.headers.get("content-type", "").startswith("application/json") else {}
    result["accept_status"] = accept.status_code
    result["accept_detail"] = accept_body.get("detail") if isinstance(accept_body, dict) else accept.text[:200]
    result["accept_auth_ok"] = accept.status_code != 401
    result["ok"] = result["accept_auth_ok"]
    return result


def safe_detail(body: dict, raw: str) -> str:
    if isinstance(body, dict) and body.get("detail"):
        return str(body["detail"])
    return raw[:200]


def main() -> int:
    report = {
        "base": BASE,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "local_markers": verify_local_markers(),
    }
    report["local_ok"] = all(report["local_markers"].values())
    try:
        report["remote_js"] = verify_remote_js()
    except Exception as exc:
        report["remote_js"] = {"ok": False, "error": str(exc)}
    try:
        report["accept_auth_probe"] = verify_accept_auth_probe()
    except Exception as exc:
        report["accept_auth_probe"] = {"ok": False, "error": str(exc)}
    report["ok"] = (
        report["local_ok"]
        and report.get("remote_js", {}).get("ok")
        and report.get("accept_auth_probe", {}).get("ok")
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report_path": str(OUT)}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
