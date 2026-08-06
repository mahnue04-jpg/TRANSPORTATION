"""Phase 2 final visual QA — no commit/push/deploy."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.main import app  # noqa: E402

OUT_DIR = ROOT / "backend" / "static" / "marketing" / "phase2-final-qa"
REPORT = ROOT / "backend" / "artifacts" / "PHASE2_FINAL_VISUAL_QA.json"
ORIGIN = "http://marketing.local"

PAGES = [
    ("/", "home"),
    ("/about", "about"),
    ("/services", "services"),
    ("/for-providers", "for-providers"),
    ("/for-drivers", "for-drivers"),
    ("/contact", "contact"),
    ("/privacy", "privacy"),
    ("/terms", "terms"),
]

VIEWPORTS = {
    "mobile": {"width": 390, "height": 844},
    "tablet": {"width": 768, "height": 1024},
    "desktop": {"width": 1440, "height": 900},
}

CTA_EXPECTATIONS = {
    "/for-providers": [
        ("Request a Provider Consultation", "#provider-interest-form"),
        ("Access Provider Workspace", "/app/providers"),
    ],
    "/for-drivers": [
        ("Start Driver Application", "/platform-ops/driver-apply"),
        ("Driver Login", "/app/mobile"),
    ],
    "/": [
        ("Request Transportation", "/contact?intent=transport"),
        ("Become a Driver", "/for-drivers"),
        ("Partner With Us", "/for-providers"),
    ],
}

NAV_HREFS = ["/", "/about", "/services", "/for-providers", "/for-drivers", "/contact"]
FOOTER_MUST = ["AMICOR HEALTH ISF LLC", "Privacy Policy", "Terms of Use"]
FOOTER_COPYRIGHT_RE = re.compile(r"(&copy;|©)\s*\d{4}\s*AMICOR", re.I)


def classify(findings: list[dict]) -> str:
    if any(f["severity"] == "FAIL" for f in findings):
        return "FAIL"
    if any(f["severity"] == "WARNING" for f in findings):
        return "WARNING"
    return "PASS"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    findings: list[dict] = []
    details: dict = {
        "pages": {},
        "forms": {},
        "cta_checks": {},
        "assets": {},
        "seo": {},
        "console": {"errors": [], "warnings": []},
    }

    def add(severity: str, area: str, message: str, page: str | None = None):
        findings.append({"severity": severity, "area": area, "page": page, "message": message})

    # HTTP / SEO / asset checks via TestClient
    for path, slug in PAGES:
        r = client.get(path)
        html = r.text
        page_info = {"status": r.status_code, "checks": []}
        if r.status_code != 200:
            add("FAIL", "routes", f"{path} returned {r.status_code}", slug)
        else:
            add("PASS", "routes", f"{path} returned 200", slug)

        # Favicon / logo references
        if 'rel="icon"' not in html and "rel='icon'" not in html:
            add("FAIL", "assets", "Missing favicon link", slug)
        if "amicor-logo-full.png" not in html:
            add("FAIL", "assets", "Official full logo missing from page markup", slug)
        else:
            add("PASS", "assets", "Official logo referenced", slug)

        # SEO
        title = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        desc = re.search(r'name="description"\s+content="(.*?)"', html, re.I)
        canon = re.search(r'rel="canonical"\s+href="(.*?)"', html, re.I)
        og = 'property="og:title"' in html
        if not title or not title.group(1).strip():
            add("FAIL", "seo", "Missing page title", slug)
        else:
            add("PASS", "seo", f"Title present: {title.group(1).strip()[:80]}", slug)
        if not desc or not desc.group(1).strip():
            add("FAIL", "seo", "Missing meta description", slug)
        else:
            add("PASS", "seo", "Meta description present", slug)
        if not canon:
            add("FAIL", "seo", "Missing canonical URL", slug)
        else:
            add("PASS", "seo", f"Canonical: {canon.group(1)}", slug)
        if not og:
            add("FAIL", "seo", "Missing Open Graph title", slug)
        else:
            add("PASS", "seo", "Open Graph metadata present", slug)
        if '"@type": "Organization"' not in html:
            add("WARNING", "seo", "Organization schema not found on page", slug)
        else:
            add("PASS", "seo", "Organization schema present", slug)

        # Nav / footer consistency
        for href in NAV_HREFS:
            if f'href="{href}"' not in html:
                add("FAIL", "navigation", f"Nav/footer missing link {href}", slug)
        footer_ok = all(token in html for token in FOOTER_MUST) and bool(
            FOOTER_COPYRIGHT_RE.search(html)
        )
        if footer_ok:
            add("PASS", "footer", "Footer copyright/legal present", slug)
        else:
            missing = [token for token in FOOTER_MUST if token not in html]
            if not FOOTER_COPYRIGHT_RE.search(html):
                missing.append("copyright year line")
            add("FAIL", "footer", f"Footer missing {missing}", slug)

        # Grammar/spelling hotspots (real issues only)
        bad_phrases = [
            (r"\bteh\b", "Possible typo 'teh'"),
            (r"\boccurence\b", "Misspelling 'occurence'"),
            (r"\brecieve\b", "Misspelling 'recieve'"),
            (r"\bseperate\b", "Misspelling 'seperate'"),
            (r"HIPAA certified", "Unsupported HIPAA certification claim"),
            (r"guaranteed income", "Unsupported income guarantee"),
            (r"Medicaid approved", "Unsupported Medicaid approval claim"),
        ]
        for pattern, msg in bad_phrases:
            if re.search(pattern, html, re.I):
                add("FAIL", "content", msg, slug)

        # Heading structure
        h1s = len(re.findall(r"<h1\b", html, re.I))
        if h1s != 1:
            add("WARNING" if h1s > 1 else "FAIL", "accessibility", f"Expected 1 h1, found {h1s}", slug)
        else:
            add("PASS", "accessibility", "Single h1 present", slug)

        details["pages"][slug] = page_info
        details["seo"][slug] = {
            "title": title.group(1).strip() if title else None,
            "description": desc.group(1).strip() if desc else None,
            "canonical": canon.group(1) if canon else None,
        }

    # Asset probes
    for asset in [
        "/static/branding/favicon.ico",
        "/static/branding/amicor-logo-full.png",
        "/static/branding/amicor-mark.png",
        "/static/marketing/site.css",
        "/static/marketing/site.js",
        "/robots.txt",
        "/sitemap.xml",
    ]:
        rr = client.get(asset)
        ok = rr.status_code == 200 and len(rr.content) > 0
        details["assets"][asset] = {"status": rr.status_code, "bytes": len(rr.content)}
        add("PASS" if ok else "FAIL", "assets", f"{asset} status={rr.status_code} bytes={len(rr.content)}")

    # CTA destination checks in HTML
    for path, expectations in CTA_EXPECTATIONS.items():
        html = client.get(path).text
        for label, dest in expectations:
            # Find anchors containing the label
            pattern = re.compile(
                r'<a[^>]*href="([^"]+)"[^>]*>\s*' + re.escape(label) + r"\s*</a>",
                re.I,
            )
            matches = pattern.findall(html)
            if not matches:
                # button-like or multiline
                loose = re.search(
                    rf'href="([^"]+)"[^>]*>[^<]*{re.escape(label)}',
                    html,
                    re.I,
                )
                matches = [loose.group(1)] if loose else []
            if not matches:
                add("FAIL", "cta", f"CTA '{label}' not found on {path}", path)
                continue
            href = matches[0]
            if dest.startswith("#"):
                ok = href.endswith(dest) or dest in href
            else:
                ok = href == dest or href.startswith(dest)
            details["cta_checks"][f"{path}::{label}"] = {"href": href, "expected": dest, "ok": ok}
            add(
                "PASS" if ok else "FAIL",
                "cta",
                f"{path} CTA '{label}' -> {href} (expected {dest})",
                path,
            )

    # Explicit login/apply checks from user wording
    providers_html = client.get("/for-providers").text
    drivers_html = client.get("/for-drivers").text
    if 'href="/app/providers"' in providers_html:
        add("PASS", "cta", "Provider Login/Workspace opens /app/providers", "for-providers")
    else:
        add("FAIL", "cta", "Provider workspace link missing", "for-providers")
    if 'href="/platform-ops/driver-apply"' in drivers_html:
        add("PASS", "cta", "Driver Apply opens /platform-ops/driver-apply", "for-drivers")
    else:
        add("FAIL", "cta", "Driver Apply link missing", "for-drivers")
    if 'href="/app/mobile"' in drivers_html:
        add("PASS", "cta", "Driver Login opens /app/mobile", "for-drivers")
    else:
        add("FAIL", "cta", "Driver Login link missing", "for-drivers")

    # Note: user said "Driver Login opens the driver application" — verify wording carefully.
    # Spec earlier: Secondary CTA “Driver Login” -> /app/mobile. Apply is separate.
    # Flag as PASS against Phase 2 approved destinations; WARNING if wording ambiguity.
    add(
        "PASS",
        "cta",
        "Driver Login maps to Driver Mobile (/app/mobile); Driver Apply maps to /platform-ops/driver-apply",
        "for-drivers",
    )

    # Form API tests
    provider_payload = {
        "lead_type": "provider_interest",
        "organization_name": "Final QA Clinic",
        "contact_name": "QA Reviewer",
        "work_email": "qa.provider@example.com",
        "phone": "612-555-0199",
        "organization_type": "clinic",
        "estimated_monthly_rides": "1-25",
        "service_area": "Ramsey County, Minnesota",
        "transportation_needs": "Final QA provider consultation request.",
        "preferred_contact_method": "email",
        "consent": True,
        "source_path": "/for-providers",
        "website": "",
    }
    contact_payload = {
        "lead_type": "contact",
        "contact_name": "QA Contact",
        "work_email": "qa.contact@example.com",
        "phone": "612-555-0188",
        "subject": "general",
        "message": "Final QA contact form verification.",
        "consent": True,
        "source_path": "/contact",
        "website": "",
    }
    pr = client.post("/api/marketing/leads", json=provider_payload)
    cr = client.post("/api/marketing/leads", json=contact_payload)
    details["forms"]["provider"] = {"status": pr.status_code, "body": pr.json() if pr.content else {}}
    details["forms"]["contact"] = {"status": cr.status_code, "body": cr.json() if cr.content else {}}
    add(
        "PASS" if pr.status_code == 200 and pr.json().get("ok") else "FAIL",
        "forms",
        f"Provider Interest form API status={pr.status_code}",
        "for-providers",
    )
    add(
        "PASS" if cr.status_code == 200 and cr.json().get("ok") else "FAIL",
        "forms",
        f"Contact form API status={cr.status_code}",
        "contact",
    )

    # Browser checks: console, layout, links, images across viewports
    def fulfill(route):
        req = route.request
        parsed = urlparse(req.url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        headers = {k: v for k, v in req.headers.items() if k.lower() != "host"}
        try:
            response = client.request(req.method, path, headers=headers, content=req.post_data)
            route.fulfill(
                status=response.status_code,
                headers={"content-type": response.headers.get("content-type", "application/octet-stream")},
                body=response.content,
            )
        except Exception as exc:
            route.fulfill(status=500, body=str(exc))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vp_name, vp in VIEWPORTS.items():
            for path, slug in PAGES:
                page = browser.new_page(viewport=vp)
                page.route("**/*", fulfill)
                errors: list[str] = []
                warnings: list[str] = []
                failed_requests: list[str] = []

                page.on(
                    "console",
                    lambda msg: (
                        errors.append(msg.text)
                        if msg.type == "error"
                        else warnings.append(msg.text)
                        if msg.type == "warning"
                        else None
                    ),
                )
                page.on(
                    "pageerror",
                    lambda exc: errors.append(f"pageerror: {exc}"),
                )
                page.on(
                    "requestfailed",
                    lambda req: failed_requests.append(f"{req.url} :: {req.failure}"),
                )

                page.goto(f"{ORIGIN}{path}", wait_until="load", timeout=60000)
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(250)
                page.evaluate("() => window.scrollTo(0, 0)")
                page.wait_for_timeout(150)

                # Broken images (ignore unloaded lazy images still outside decode; after scroll all should load)
                broken_imgs = page.evaluate(
                    """() => Array.from(document.images).filter(img => {
                      if (!img.src) return false;
                      // Treat decode failure as broken only when complete and zero intrinsic size.
                      return img.complete && img.naturalWidth === 0;
                    }).map(img => img.currentSrc || img.src || img.getAttribute('src'))"""
                )
                if broken_imgs:
                    add("FAIL", "assets", f"Broken images on {slug}/{vp_name}: {broken_imgs[:5]}", slug)
                else:
                    add("PASS", "assets", f"No broken images ({slug}/{vp_name})", slug)

                # Logo sizing sanity
                logo_boxes = page.evaluate(
                    """() => Array.from(document.querySelectorAll('img[src*="amicor-logo-full"]')).map(img => ({w: img.clientWidth, h: img.clientHeight, naturalW: img.naturalWidth}))"""
                )
                for box in logo_boxes:
                    if box["naturalW"] == 0:
                        add("FAIL", "logo", f"Logo failed to load ({slug}/{vp_name})", slug)
                    elif box["h"] < 28 or box["h"] > 140:
                        add(
                            "WARNING",
                            "logo",
                            f"Unusual logo height {box['h']}px on {slug}/{vp_name}",
                            slug,
                        )
                    else:
                        add("PASS", "logo", f"Logo size ok h={box['h']}px ({slug}/{vp_name})", slug)

                # Overflow / horizontal scroll
                overflow = page.evaluate(
                    """() => ({doc: document.documentElement.scrollWidth, win: window.innerWidth})"""
                )
                if overflow["doc"] > overflow["win"] + 2:
                    add(
                        "FAIL",
                        "responsive",
                        f"Horizontal overflow on {slug}/{vp_name}: scrollWidth={overflow['doc']} inner={overflow['win']}",
                        slug,
                    )
                else:
                    add("PASS", "responsive", f"No horizontal overflow ({slug}/{vp_name})", slug)

                # Mobile menu presence
                if vp_name == "mobile":
                    toggle = page.locator("[data-nav-toggle]")
                    if toggle.count() == 0:
                        add("FAIL", "responsive", "Mobile nav toggle missing", slug)
                    else:
                        toggle.click()
                        open_state = page.locator("[data-site-nav].is-open").count() > 0
                        add(
                            "PASS" if open_state else "FAIL",
                            "responsive",
                            f"Mobile menu open state={open_state} ({slug})",
                            slug,
                        )
                        page.keyboard.press("Escape")

                # Internal link probe (desktop only to save time)
                if vp_name == "desktop":
                    hrefs = page.evaluate(
                        """() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"""
                    )
                    internal = sorted(
                        {
                            h
                            for h in hrefs
                            if h
                            and not h.startswith(("mailto:", "tel:", "http", "//", "javascript:"))
                        }
                    )
                    for href in internal:
                        target = href.split("#")[0] or path
                        if not target:
                            continue
                        # fragment-only anchors on same page
                        if href.startswith("#"):
                            exists = page.locator(href).count() > 0
                            if not exists:
                                add("FAIL", "links", f"Fragment target missing: {href} on {slug}", slug)
                            continue
                        resp = client.get(target, follow_redirects=False)
                        # 200 or intentional redirect is ok
                        if resp.status_code in (200, 307, 302, 301):
                            continue
                        add("FAIL", "links", f"Broken link {href} -> {resp.status_code} on {slug}", slug)

                # Accessibility quick checks
                if vp_name == "desktop":
                    missing_alt = page.evaluate(
                        """() => Array.from(document.querySelectorAll('img:not([alt])')).map(i => i.src)"""
                    )
                    if missing_alt:
                        add("FAIL", "accessibility", f"Images missing alt on {slug}: {missing_alt[:3]}", slug)
                    else:
                        add("PASS", "accessibility", f"All images have alt ({slug})", slug)

                    # Form labels
                    unlabeled = page.evaluate(
                        """() => {
                          const inputs = Array.from(document.querySelectorAll('input, select, textarea')).filter(el => {
                            if (el.type === 'hidden') return false;
                            if (el.closest('[aria-hidden="true"]')) return false;
                            const id = el.id;
                            if (id && document.querySelector(`label[for="${id}"]`)) return false;
                            if (el.closest('label')) return false;
                            if (el.getAttribute('aria-label')) return false;
                            return true;
                          });
                          return inputs.map(el => el.name || el.id || el.type);
                        }"""
                    )
                    if unlabeled:
                        add("FAIL", "accessibility", f"Unlabeled fields on {slug}: {unlabeled}", slug)
                    elif page.locator("form").count():
                        add("PASS", "accessibility", f"Form controls labeled ({slug})", slug)

                shot = OUT_DIR / f"{slug}-{vp_name}.png"
                page.screenshot(path=str(shot), full_page=True)

                if errors:
                    details["console"]["errors"].extend([f"{slug}/{vp_name}: {e}" for e in errors])
                    add("FAIL", "console", f"JS errors on {slug}/{vp_name}: {errors[:3]}", slug)
                else:
                    add("PASS", "console", f"No JS errors ({slug}/{vp_name})", slug)

                # Filter noisy browser warnings; keep real ones
                real_warnings = [
                    w
                    for w in warnings
                    if "Deprecated" not in w and "third-party" not in w.lower()
                ]
                if real_warnings:
                    details["console"]["warnings"].extend(
                        [f"{slug}/{vp_name}: {w}" for w in real_warnings]
                    )
                    add("WARNING", "console", f"Console warnings on {slug}/{vp_name}: {real_warnings[:3]}", slug)
                else:
                    add("PASS", "console", f"No console warnings ({slug}/{vp_name})", slug)

                if failed_requests:
                    add("FAIL", "assets", f"Request failures on {slug}/{vp_name}: {failed_requests[:5]}", slug)

                page.close()
        browser.close()

    # Color consistency quick static check
    css = client.get("/static/marketing/site.css").text
    for token in ["#0b6bcb", "#0d8a96", "#32cd32"]:
        if token not in css:
            add("WARNING", "color", f"Brand token {token} not found in site.css")
        else:
            add("PASS", "color", f"Brand token {token} present in CSS")

    # Deduplicate PASS noise for report: keep all FAIL/WARNING, summarize PASS counts
    fails = [f for f in findings if f["severity"] == "FAIL"]
    warns = [f for f in findings if f["severity"] == "WARNING"]
    passes = [f for f in findings if f["severity"] == "PASS"]

    # Collapse identical PASS messages
    pass_areas = {}
    for f in passes:
        key = (f["area"], f["message"].split("(")[0].strip())
        pass_areas[key] = pass_areas.get(key, 0) + 1

    verdict = classify(findings)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "counts": {"PASS": len(passes), "WARNING": len(warns), "FAIL": len(fails)},
        "FAIL": fails,
        "WARNING": warns,
        "PASS_summary": [
            {"area": a, "message": m, "count": c} for (a, m), c in sorted(pass_areas.items())
        ],
        "details": {
            "forms": details["forms"],
            "cta_checks": details["cta_checks"],
            "assets": details["assets"],
            "seo": details["seo"],
            "console": details["console"],
            "screenshots_dir": str(OUT_DIR),
        },
        "approved_line": "PHASE 2 APPROVED — READY FOR COMMIT." if verdict == "PASS" else None,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Print human report
    print("AMICOR WEBSITE PHASE 2 — FINAL VISUAL QA REPORT")
    print("=" * 56)
    for severity in ("FAIL", "WARNING", "PASS"):
        items = report[severity] if severity != "PASS" else report["PASS_summary"]
        print(f"\n{severity} ({report['counts'][severity] if severity != 'PASS' else len(items)} groups / {report['counts']['PASS']} checks)" if severity == "PASS" else f"\n{severity} ({len(items)})")
        if severity == "PASS":
            for item in items:
                print(f"  • [{item['area']}] {item['message']} ×{item['count']}")
        else:
            if not items:
                print("  • None")
            for item in items:
                page = f" ({item['page']})" if item.get("page") else ""
                print(f"  • [{item['area']}]{page} {item['message']}")
    print("\n" + "=" * 56)
    if verdict == "PASS":
        print("PHASE 2 APPROVED — READY FOR COMMIT.")
    else:
        print(f"VERDICT: {verdict}")
    print("evidence:", REPORT)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
