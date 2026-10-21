"""The fictional Casting demo stays in the browser and the sandbox keeps its gates."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "static/nova-creative/casting-pilot-demo.html"
SANDBOX = ROOT / "static/nova-creative/casting-sandbox.html"
PREVIEW = ROOT / "static/nova-creative/casting-preview.html"


def test_public_preview_route_keeps_applications_off():
    page = Path(__file__).resolve().parents[2] / "website" / "casting" / "index.html"
    html = page.read_text(encoding="utf-8")
    assert "Public applications are off" in html
    assert "Messages are not sent" in html
    assert "<form" not in html.lower()
    assert 'name="viewport"' in html
    assert "noindex" in html
    assert "fetch(" not in html
    assert "/static/nova-creative/casting-sandbox.html" not in html
    assert "Signed-in sandbox: not hosted on this public preview" in html
    assert "Public intake: off" in html
    assert 'lang="en"' in html
    assert 'href="#main"' in html
    assert 'aria-controls="site-nav"' in html
    assert 'aria-expanded="false"' in html


def test_demo_is_labeled_and_offline():
    html = DEMO.read_text(encoding="utf-8")
    assert "Demo / Early Access" in html
    assert "Harborlight" in html
    assert "$2,400" in html
    assert "not an invoice and not a signed agreement" in html
    assert "independent producers and online creators" in html
    assert "no partnership with Zeus, Netflix" in html
    assert "Nothing was submitted" in html
    assert "No invitation was delivered" in html
    assert "Delivered: false" in html
    assert "America/New_York" in html
    assert "Applicant does not meet the minimum age" in html
    assert 'type="file"' not in html
    assert "fetch(" not in html
    assert "localStorage" not in html
    assert "XMLHttpRequest" not in html
    assert 'lang="en"' in html
    assert 'name="viewport"' in html
    assert "@media (max-width: 800px)" in html
    assert 'aria-live="polite"' in html
    assert "<label>" in html or "<label " in html


def test_sandbox_pilot_controls_keep_the_existing_journey():
    sandbox = SANDBOX.read_text(encoding="utf-8")
    preview = PREVIEW.read_text(encoding="utf-8")
    assert "fetch(" not in preview
    assert "/intake" in sandbox
    assert "/review-queue" in sandbox
    assert "/pilot-demo" in sandbox
    assert "Revoke consent" in sandbox
    assert "Demo / Early Access" in sandbox
    assert "No invitation was sent" in sandbox
    assert 'id="media-file" type="file"' in sandbox
    assert "Nothing was submitted" in sandbox
    assert "No relationship or integration with Zeus" in sandbox
    assert "Reload saved pilot" in sandbox
    assert "/pilot-snapshot" in sandbox
    assert "Reloaded from the server" in sandbox
    restore = sandbox.split("async function restorePilot", 1)[1].split("$(\"reload-pilot\")", 1)[0]
    assert "applicationId = intake.id" in restore
    assert "intake.role_id" in restore
    assert "row.application_id === applicationId" in restore
    assert "Applicant does not meet the minimum age" in sandbox
    assert 'aria-live="polite"' in sandbox
    assert "@media (max-width: 640px)" in sandbox
    assert "width: 100%" in sandbox
    assert "External delivery:" in sandbox
    assert "focus-visible" in sandbox
    assert "/pilot-audit?limit=50" in sandbox
    assert "JSON.stringify(sheet" not in sandbox
    assert "overflow-wrap: anywhere" in sandbox
    assert "grid-template-columns: 1fr" in sandbox
    assert 'id="faq-question"' in sandbox
    assert "/subscriber-faq" in sandbox
    faq = sandbox.split('aria-label="Subscriber FAQ"', 1)[1].split("<section", 1)[0]
    assert 'type="password"' not in faq
    assert "cc-number" not in faq
    assert "billing" in faq.lower()
    assert "No card, password, or account credential is collected" in faq
    assert "External delivery: false" in faq
    assert "<form" not in (Path(__file__).resolve().parents[2] / "website" / "casting" / "index.html").read_text(encoding="utf-8").lower()
