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
