"""Direct-URL and claim checks for the signed-in Nova access page."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = "https://amicor-health-isf-py.onrender.com"
ACCESS = ROOT / "nova-access" / "index.html"
CONFIG = ROOT / "assets" / "js" / "site-config.js"


def _pages() -> list[Path]:
    return [ROOT / "index.html", *ROOT.glob("*/index.html"), *ROOT.glob("*/*/index.html")]


def test_nova_access_direct_url_exists() -> None:
    html = ACCESS.read_text(encoding="utf-8")
    assert "<title>Open Nova — Signed-in AMICOR workspaces</title>" in html
    assert 'rel="canonical" href="https://getamicor.com/nova-access/"' in html
    assert 'href="/nova-access/" aria-current="page"' in html
    assert html.count("<h1>") == 1
    assert 'href="#main"' in html


def test_signed_in_targets_are_existing_app_routes() -> None:
    html = ACCESS.read_text(encoding="utf-8")
    for href in (
        f"{APP}/nova?signin=1",
        f"{APP}/nova/work",
        f"{APP}/nova/today",
        f"{APP}/nova/creative",
        f"{APP}/nova/anonymous-agent",
    ):
        assert f'href="{href}"' in html
    assert "Sign in to review Work &amp; Revenue" in html
    assert "Open the sandbox demo" in html
    assert "does not send email, update a CRM, charge money, or submit work" in html


def test_status_labels_are_text_not_color_alone() -> None:
    html = ACCESS.read_text(encoding="utf-8")
    for label in ("Account access", "Supervised release", "Early access"):
        assert f">{label}</span>" in html
    assert "Casting intake and public auditions are not offered" in html
    assert "does not collect payment" in html


def test_nav_cta_points_at_the_access_page() -> None:
    for path in _pages():
        html = path.read_text(encoding="utf-8")
        assert 'class="nav-cta" href="/nova-access/"' in html, path
        assert "Try Nova" not in html, path


def test_held_back_surfaces_stay_unpublished() -> None:
    config = CONFIG.read_text(encoding="utf-8")
    assert "firstCustomerFunnel: true" not in config
    assert "firstCustomerFunnel stays off" in config
    assert not (ROOT / "start" / "index.html").exists()
    assert not (ROOT / "guides" / "research-memo-setup" / "index.html").exists()
    blob = "\n".join(path.read_text(encoding="utf-8").lower() for path in _pages())
    for token in ("apply now", "auto-appl", "payment received", "stripe.com", 'href="/casting', "href=\"/audition"):
        assert token not in blob, token
    assert "casting intake and public auditions are not offered" in blob
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    assert "https://getamicor.com/nova-access/" in sitemap
    assert "https://getamicor.com/start/" not in sitemap


def test_work_revenue_does_not_offer_live_submission() -> None:
    html = (ROOT / "work-revenue" / "index.html").read_text(encoding="utf-8")
    assert "Early Access / In Development" in html
    assert 'href="/nova-access/#work-revenue"' in html
    assert "does not submit applications" in html
    assert f"{APP}/nova/anonymous-agent" not in html


def main() -> None:
    tests = [
        test_nova_access_direct_url_exists,
        test_signed_in_targets_are_existing_app_routes,
        test_status_labels_are_text_not_color_alone,
        test_nav_cta_points_at_the_access_page,
        test_held_back_surfaces_stay_unpublished,
        test_work_revenue_does_not_offer_live_submission,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"TESTS_PASSED={len(tests)}")


if __name__ == "__main__":
    main()
