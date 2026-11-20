"""Static compliance/privacy checks for the CFSS planning prototype.

This test never opens a browser, sends financial information, or contacts DHS.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "cfss-copilot" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "cfss-copilot" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "cfss-copilot" / "style.css").read_text(encoding="utf-8")

def test_browser_local_without_upload() -> None:
    assert "localStorage" not in HTML + JS
    assert '<script src="./app.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="./style.css">' in HTML
    assert "<script>" not in HTML
    assert "<style>" not in HTML
    assert "script-src 'self'" in HTML
    assert "style-src 'self'" in HTML
    assert ".fieldgrid" in CSS
    assert "sessionStorage" not in HTML + JS
    assert "fetch(" not in HTML + JS
    assert "XMLHttpRequest" not in HTML + JS
    assert "navigator.sendBeacon" not in HTML + JS
    assert "googletagmanager.com" not in HTML
    assert "googletagmanager" not in HTML.lower()
    assert "connect-src \'none\'" in HTML
    assert "third-party analytics" in HTML
    assert "<form" in HTML
    assert "type=\"submit\"" in HTML
    assert "No accounts or uploads" in HTML

def test_program_boundaries() -> None:
    assert "Not an official DHS or FMS system" in HTML
    assert "does not establish eligibility" in HTML
    assert "not confirmation that funds or purchases are available or approved" in JS
    assert "financial management services (FMS)" in HTML
    assert "Do not enter names" in HTML
    assert "individual spending amount" in HTML
    assert "cumulative balance" in HTML
    assert "getamicor.com/early-access/?product=CFSS%20Budget%20Co-Pilot" in HTML
    assert "does not receive your entries" in HTML
    assert "No payments accepted" in HTML
    assert "tiered wage floor" in HTML
    assert "separate authorization line" in HTML
    assert "Do not double-count" in HTML
    assert "no wages, schedules, goods, or services are approved" in HTML

def test_essential_values_and_scenario() -> None:
    for f in (
        "budget", "months", "elapsed", "spent", "wage", "hours",
        "burden", "other", "onetime", "altWage", "altHours",
    ):
        assert re.search(rf'id="{f}"', HTML)
    assert "values.wage*values.hours*52/12" in JS
    assert "values.spent+future" in JS
    assert "values.budget-projected" in JS
    assert 'values.months-values.elapsed' in JS
    assert 'values.spent>v.budget' not in HTML
    assert "v.spent>v.budget" not in HTML
    assert "FMS-reported spending already exceeds the entered authorization" in JS
    assert "maxHours" in JS
    assert "form.requestSubmit()" in JS
    assert 'exampleActive=true' in JS
    assert 'link.download="cfss-budget-planning-scenario.csv"' in JS

def test_no_public_customer_identifiers() -> None:
    assert "type=\"password\"" not in HTML
    assert "social security" not in HTML.lower()
    assert "name=\"person" not in HTML.lower()
    assert "name=\"ssn" not in HTML.lower()
    assert "api/leads" not in HTML + JS
    assert "stripe" not in (HTML + JS).lower()

if __name__ == "__main__":
    tests=[test_browser_local_without_upload,test_program_boundaries,test_essential_values_and_scenario,test_no_public_customer_identifiers]
    for t in tests:
        t()
        print("PASS",t.__name__)
    print(f"CFSS_STATIC_CHECKS_PASSED={len(tests)}")
