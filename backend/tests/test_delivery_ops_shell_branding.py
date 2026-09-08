"""Contract checks for AMICOR Delivery ops-shell branding and render stubs."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS_JS = (ROOT / "static" / "ops-shell.js").read_text(encoding="utf-8")
OPS_HTML = (ROOT / "static" / "ops-shell.html").read_text(encoding="utf-8")
APPLY_HTML = (ROOT / "static" / "platform-ops" / "driver-apply.html").read_text(encoding="utf-8")


def test_ops_shell_defines_delivery_render_stubs() -> None:
    for name in (
        "function captureDeliveryProofDrafts",
        "function takeLiveDeliveryForm",
        "function putLiveDeliveryForm",
        "function renderDeliveryOfferCardsHtml",
        "function renderDeliveryActiveJobCardHtml",
    ):
        assert name in OPS_JS


def test_delivery_facing_copy_does_not_say_amicor_health() -> None:
    assert "AMICOR Delivery" in OPS_HTML
    assert "AMICOR Delivery Operations" in OPS_HTML
    assert "Riders / Patients" not in OPS_HTML
    assert "Search deliveries, drivers, customers" in OPS_HTML
    assert 'title: "Customer App"' in OPS_JS
    assert "AMICOR Delivery — Customer Request" in OPS_JS
    assert "healthcare-first rider surface" not in OPS_JS
    assert "Billing & Earnings" in OPS_JS
    assert "Driver Application | AMICOR Delivery" in APPLY_HTML
    assert "Become an AMICOR Delivery Driver" in APPLY_HTML
