"""The working sandbox page is separate from the fictional preview."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "static" / "nova-creative" / "index.html"
PREVIEW = ROOT / "static" / "nova-creative" / "casting-preview.html"
SANDBOX = ROOT / "static" / "nova-creative" / "casting-sandbox.html"


def test_sandbox_page_is_linked_and_the_fictional_preview_stays_offline():
    studio = STUDIO.read_text(encoding="utf-8")
    preview = PREVIEW.read_text(encoding="utf-8")
    sandbox = SANDBOX.read_text(encoding="utf-8")
    assert 'href="/static/nova-creative/casting-preview.html"' in studio
    assert 'href="/static/nova-creative/casting-sandbox.html"' in studio
    assert "fetch(" not in preview
    assert "fetch(" in sandbox
    assert "/api/nova/casting/readiness" in sandbox
    assert "sandbox_writes_enabled" in sandbox
    assert "amicor_nova_creative_token" in sandbox
    assert 'type="file"' not in sandbox
    assert "No relationship or integration with Zeus" in sandbox
    assert "Nothing was submitted" in sandbox
    for label in ("Loading", "error", "Withdraw", "Shortlist", "Callback"):
        assert label in sandbox
