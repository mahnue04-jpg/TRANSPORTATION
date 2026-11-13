"""Static contract checks for Growth Agent summary in existing Nova Workspace."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static" / "nova-workspace"


def test_growth_overview_is_in_workspace_navigation():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'href="#growth-agent-overview"' in html
    assert 'id="growth-agent-overview"' in html
    assert 'id="growth-agent-summary"' in html
    assert 'id="growth-agent-status"' in html
    assert "/static/nova-workspace/growth-overview.js" in html


def test_growth_overview_uses_session_and_only_reads_owner_apis():
    script = (STATIC / "growth-overview.js").read_text(encoding="utf-8")
    assert "window.AmiCorSession" in script
    assert "getAuthHeaders" in script
    for route in ('"/flags"', '"/leads"', '"/conversations"', '"/appointments"'):
        assert route in script
    assert 'credentials: "same-origin"' in script
    assert "response.status === 403" in script
    assert "Mock / no live delivery" in script
    assert "Array.isArray(leads.leads)" in script
    assert "Array.isArray(appointments.appointments)" in script
    assert "method: \"POST\"" not in script
    assert "method: \"PATCH\"" not in script


def test_growth_overview_handles_login_and_stale_responses():
    workspace = (STATIC / "workspace.js").read_text(encoding="utf-8")
    growth = (STATIC / "growth-overview.js").read_text(encoding="utf-8")
    assert 'window.dispatchEvent(new Event("nova:workspace-signed-in"))' in workspace
    assert 'window.addEventListener("nova:workspace-signed-in", load)' in growth
    assert "setTimeout(load" not in growth
    assert "const tokenAtStart = currentToken()" in growth
    assert "request !== requestId" in growth
    assert "currentToken() === tokenAtStart" in growth
    assert "requestId++" in growth


def test_growth_overview_checks_tenant_identity_and_prevents_old_refresh_status():
    growth = (STATIC / "growth-overview.js").read_text(encoding="utf-8")
    assert "getOrganizationId" in growth
    assert "currentOrganization() !== organizationAtStart" in growth
    assert "currentOrganization() === organizationAtStart" in growth
    assert "if (request !== requestId) return;" in growth


def test_growth_handoff_review_is_read_only_and_escapes_untrusted_subjects():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    growth = (STATIC / "growth-overview.js").read_text(encoding="utf-8")
    assert 'id="growth-agent-review"' in html
    assert 'id="growth-agent-review-list"' in html
    assert 'row.handler === "human" || row.status === "handed_off"' in growth
    assert 'subject.textContent =' in growth
    assert 'item.append(subject, flag)' in growth
    assert 'reviewList.appendChild(item)' in growth
    assert 'handoff.is_synthetic_demo === true' in growth
    assert 'reviewPanel.hidden = true' in growth or 'byId("growth-agent-review").hidden = true' in growth
