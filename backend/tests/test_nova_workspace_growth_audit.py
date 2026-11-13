"""Contract tests for read-only Workspace workflow audit panel."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static" / "nova-workspace"

def test_workflow_audit_is_loaded_with_a_manual_review_button():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="growth-agent-audit-load"' in html
    assert 'id="growth-agent-audit-status"' in html
    assert 'id="growth-agent-audit-list"' in html
    assert "/static/nova-workspace/growth-audit.js" in html

def test_workflow_audit_is_owner_scoped_and_read_only():
    js = (STATIC / "growth-audit.js").read_text(encoding="utf-8")
    assert 'window.AmiCorSession' in js
    assert 'getOrganizationId' in js
    assert '"/api/nova/growth-agent/audit?limit=50"' in js
    assert 'credentials: "same-origin"' in js
    assert 'response.status === 403' in js
    assert 'startsWith("workflow.")' in js
    assert 'item.textContent =' in js
    assert 'request !== requestId' in js
    assert 'isSameOwner(state)' in js
    assert 'method: "POST"' not in js
    assert 'method: "PATCH"' not in js


def test_visible_audit_clears_after_org_change_or_new_session():
    js = (STATIC / "growth-audit.js").read_text(encoding="utf-8")
    assert 'visibleOwner = { token: state.token, org: state.org }' in js
    assert 'if (visibleOwner && !isSameOwner(visibleOwner))' in js
    assert 'window.addEventListener("focus", verifyVisibleOwner)' in js
    assert 'document.addEventListener("visibilitychange", verifyVisibleOwner)' in js
