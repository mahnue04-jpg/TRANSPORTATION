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
    assert 'type="file"' not in preview
    assert 'id="media-file" type="file"' in sandbox
    assert "/media/file" in sandbox
    assert "/content" in sandbox
    assert "URL.createObjectURL" in sandbox
    assert "sandbox_private_media_enabled" in sandbox
    assert "Structural scan only. Antivirus is not ready." in sandbox
    assert 'aria-live="polite"' in sandbox
    assert "No relationship or integration with Zeus" in sandbox
    assert "Nothing was submitted" in sandbox
    assert "Save campaign edits" in sandbox
    assert "Create sandbox organization" in sandbox
    assert "Resume saved application" in sandbox
    for label in ("Loading", "error", "Withdraw", "Shortlist", "Callback"):
        assert label in sandbox


def test_casting_auth_uses_shared_session_and_distinguishes_unauthorized():
    sandbox = SANDBOX.read_text(encoding="utf-8")
    assert '<script src="/static/ux/sessionManager.js"></script>' in sandbox
    assert 'shared.ensureReady()' in sandbox
    assert 'shared.authFetch(path' in sandbox
    assert 'shared.start({' in sandbox
    assert 'shared.applyAuthTokens(body)' in sandbox
    assert 'shared.setSession(' not in sandbox
    assert 'if (isLogin) detail = "Nova rejected these sign-in credentials (401).' in sandbox
    assert 'Casting session is unauthorized (401).' in sandbox
    assert 'id="create-organization" disabled' in sandbox
    assert 'setOrganizationReadiness(false,' in sandbox
