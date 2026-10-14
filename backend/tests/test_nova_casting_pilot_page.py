"""The fictional Casting demo stays in the browser and the sandbox keeps its gates."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "static/nova-creative/casting-pilot-demo.html"
SANDBOX = ROOT / "static/nova-creative/casting-sandbox.html"
PREVIEW = ROOT / "static/nova-creative/casting-preview.html"


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
