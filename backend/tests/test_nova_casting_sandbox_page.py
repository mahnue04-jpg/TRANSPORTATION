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
    assert "function showSandboxOff" in sandbox
    assert "function syncAuthControls" in sandbox
    assert "401 Unauthorized" in sandbox
    assert "409 Conflict" in sandbox
    assert 'id="signed-out-login"' in sandbox
    assert 'id="signed-in-auth"' in sandbox
    assert "Signed in." in sandbox
    assert "This email already has a Nova account. Sign in instead. Nothing was created." in sandbox
    assert "failure.status = response.status" in sandbox
    assert "Save campaign edits" in sandbox
    assert "Create sandbox organization" in sandbox
    assert 'id="create-account"' in sandbox
    assert 'id="send-reset"' in sandbox
    assert 'id="update-password"' in sandbox
    assert "/api/nova/signup/free" in sandbox
    assert "/api/auth/forgot-password" in sandbox
    assert "/api/auth/reset-password" in sandbox
    assert "No message was sent." in sandbox
    assert "Sign in with Google" not in sandbox
    assert "accounts.google.com" not in sandbox
    assert "This preview keeps its own accounts." in sandbox
    assert "A main Nova sign-in is not in this database." in sandbox
    assert '"/api/auth/login"' in sandbox
    assert "Request error" not in sandbox
    assert 'id="signed-in-auth" class="hidden" hidden' in sandbox
    guard = (ROOT / "static" / "nova-creative" / "auth-session-guard.js").read_text(encoding="utf-8")
    assert "Nova rejected these sign-in credentials" not in guard
    assert "Resume saved application" in sandbox
    for label in ("Loading", "error", "Withdraw", "Shortlist", "Callback"):
        assert label in sandbox
