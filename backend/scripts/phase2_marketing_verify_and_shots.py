"""Phase 2 local verification + approval screenshots (no deploy)."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

OUT_DIR = ROOT / "backend" / "static" / "marketing" / "phase2-screenshots"
EVIDENCE = ROOT / "backend" / "artifacts" / "phase2_marketing_verify.json"
BASE = "http://127.0.0.1:8765"


def api_checks(client: TestClient) -> dict:
    results = {"routes": {}, "ctas": {}, "forms": {}, "seo": {}, "app_preserved": {}}

    for path in [
        "/",
        "/about",
        "/services",
        "/for-providers",
        "/for-drivers",
        "/contact",
        "/privacy",
        "/terms",
        "/robots.txt",
        "/sitemap.xml",
        "/workspace",
        "/app/providers",
        "/app/mobile",
        "/platform-ops/driver-apply",
    ]:
        r = client.get(path, follow_redirects=False)
        results["routes"][path] = {
            "status": r.status_code,
            "ok": r.status_code == 200,
            "surface": r.headers.get("x-amicor-surface"),
        }

    # Legacy aliases must remain redirects into /app
    for path, dest in (("/providers", "/app/providers"), ("/drivers", "/app/drivers")):
        r = client.get(path, follow_redirects=False)
        results["app_preserved"][path] = {
            "status": r.status_code,
            "location": r.headers.get("location"),
            "ok": r.status_code == 307 and r.headers.get("location") == dest,
        }

    provider = client.get("/for-providers")
    driver = client.get("/for-drivers")
    home = client.get("/")
    results["ctas"] = {
        "provider_primary": "#provider-interest-form" in provider.text
        and "Request a Provider Consultation" in provider.text,
        "provider_workspace": 'href="/app/providers"' in provider.text,
        "driver_apply": 'href="/platform-ops/driver-apply"' in driver.text,
        "driver_login": 'href="/app/mobile"' in driver.text,
        "home_trust": "Transportation Coordination Built Around Care" in home.text,
        "provider_trust": "Transportation Coordination Built Around Care" in provider.text,
        "driver_trust": "Transportation Coordination Built Around Care" in driver.text,
        "provider_faq_schema": '"@type": "FAQPage"' in provider.text,
        "driver_faq_schema": '"@type": "FAQPage"' in driver.text,
        "no_hipaa_claim": "HIPAA certified" not in provider.text.lower(),
        "no_guaranteed_income": "guaranteed income" not in driver.text.lower(),
    }

    results["seo"] = {
        "canonical_home": 'rel="canonical"' in home.text,
        "og_title": 'property="og:title"' in home.text,
        "org_schema": '"@type": "Organization"' in home.text,
        "robots": client.get("/robots.txt").status_code == 200
        and "Sitemap:" in client.get("/robots.txt").text,
        "sitemap": client.get("/sitemap.xml").status_code == 200
        and "/for-providers" in client.get("/sitemap.xml").text,
    }

    # Valid provider lead
    good = client.post(
        "/api/marketing/leads",
        json={
            "lead_type": "provider_interest",
            "organization_name": "Phase2 Test Clinic",
            "contact_name": "Taylor Provider",
            "work_email": "taylor.provider@example.com",
            "phone": "612-555-0100",
            "organization_type": "clinic",
            "estimated_monthly_rides": "26-75",
            "service_area": "Hennepin County, Minnesota",
            "transportation_needs": "Dialysis and discharge coordination support.",
            "preferred_contact_method": "email",
            "consent": True,
            "source_path": "/for-providers",
            "website": "",
        },
    )
    # Missing consent
    bad = client.post(
        "/api/marketing/leads",
        json={
            "lead_type": "provider_interest",
            "organization_name": "No Consent Org",
            "contact_name": "No Consent",
            "work_email": "noconsent@example.com",
            "phone": "612-555-0101",
            "organization_type": "hospital",
            "transportation_needs": "Needs rides",
            "preferred_contact_method": "phone",
            "consent": False,
            "website": "",
        },
    )
    # Honeypot
    spam = client.post(
        "/api/marketing/leads",
        json={
            "lead_type": "contact",
            "contact_name": "Bot",
            "work_email": "bot@example.com",
            "message": "spam",
            "consent": True,
            "website": "http://spam.example",
        },
    )
    good_body = good.json() if good.headers.get("content-type", "").startswith("application/json") else {}
    spam_body = spam.json() if spam.headers.get("content-type", "").startswith("application/json") else {}
    results["forms"] = {
        "provider_lead_status": good.status_code,
        "provider_lead_ok": good.status_code == 200 and bool(good_body.get("ok")),
        "provider_lead_id": (good_body.get("data") or {}).get("lead_id"),
        "missing_consent_status": bad.status_code,
        "missing_consent_rejected": bad.status_code == 422,
        "honeypot_status": spam.status_code,
        "honeypot_filtered": spam.status_code == 200
        and bool((spam_body.get("data") or {}).get("spam_filtered")),
    }
    return results


def take_screenshots() -> dict:
    import subprocess
    import urllib.request

    from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shots: dict[str, object] = {}
    console_errors: list[str] = []

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    env["AMICOR_SKIP_WMI_PLATFORM_QUERY"] = "1"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT / "backend"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        ready = False
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError(f"uvicorn exited early with code {proc.returncode}")
            try:
                with urllib.request.urlopen(f"{BASE}/api/health", timeout=1) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.25)
        if not ready:
            raise RuntimeError("Local uvicorn failed to become ready on :8765")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            targets = [
                ("provider-desktop", "/for-providers", 1440, 900),
                ("provider-mobile", "/for-providers", 390, 844),
                ("driver-desktop", "/for-drivers", 1440, 900),
                ("driver-mobile", "/for-drivers", 390, 844),
                ("home-trust", "/", 1440, 900),
            ]
            for slug, path, width, height in targets:
                page = browser.new_page(viewport={"width": width, "height": height})

                def _on_console(msg, slug=slug):
                    if msg.type == "error":
                        console_errors.append(f"{slug}: {msg.text}")

                page.on("console", _on_console)
                page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=60000)
                if slug == "home-trust":
                    page.locator("#trust-heading").scroll_into_view_if_needed()
                    time.sleep(0.35)
                out = OUT_DIR / f"{slug}.png"
                page.screenshot(path=str(out), full_page=True)
                shots[slug] = str(out)
                page.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    shots["console_errors"] = console_errors
    if console_errors:
        raise RuntimeError("Console errors: " + " | ".join(console_errors[:8]))
    return shots


def main() -> int:
    client = TestClient(app)
    results = api_checks(client)
    shot_error = None
    try:
        results["screenshots"] = take_screenshots()
    except Exception as exc:
        shot_error = str(exc)
        results["screenshots"] = {"error": shot_error}

    route_ok = all(v.get("ok") for k, v in results["routes"].items() if k.startswith("/"))
    # workspace and app routes included
    preserved_ok = all(v.get("ok") for v in results["app_preserved"].values())
    cta_ok = all(bool(v) for v in results["ctas"].values())
    form_ok = (
        results["forms"].get("provider_lead_ok")
        and results["forms"].get("missing_consent_rejected")
        and results["forms"].get("honeypot_filtered")
    )
    seo_ok = all(bool(v) for v in results["seo"].values())
    shots_ok = isinstance(results.get("screenshots"), dict) and "error" not in results["screenshots"]

    results["summary"] = {
        "routes_ok": route_ok,
        "preserved_ok": preserved_ok,
        "ctas_ok": cta_ok,
        "forms_ok": bool(form_ok),
        "seo_ok": seo_ok,
        "screenshots_ok": shots_ok,
        "verdict": "PASS"
        if all([route_ok, preserved_ok, cta_ok, form_ok, seo_ok, shots_ok])
        else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results["summary"], indent=2))
    print("evidence:", EVIDENCE)
    if shots_ok:
        print("screenshots:", OUT_DIR)
    return 0 if results["summary"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
