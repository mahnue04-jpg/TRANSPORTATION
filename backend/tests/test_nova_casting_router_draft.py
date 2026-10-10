"""Static test: dormant casting router reuses Nova auth and is never registered."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app/core/nova/creative_studio/casting_router_draft.py"


def test_dormant_casting_router_requires_existing_nova_login():
    source = ROUTER.read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    creative = (ROOT / "app/core/nova/creative_studio/router.py").read_text(encoding="utf-8")
    assert "get_current_user_context" in source
    assert "Depends(get_current_user_context)" in source
    assert '"enabled": False' in source
    assert '"applications_enabled": False' in source
    assert '"media_uploads_enabled": False' in source
    assert "casting_router_draft" not in main
    assert "casting_router_draft" not in creative
