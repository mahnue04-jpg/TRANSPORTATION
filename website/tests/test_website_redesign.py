"""Website-only route, link, and claim checks for the Nova redesign."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    "/": ROOT / "index.html",
    "/products/": ROOT / "products" / "index.html",
    "/solutions/": ROOT / "solutions" / "index.html",
    "/pricing/": ROOT / "pricing" / "index.html",
    "/resources/": ROOT / "resources" / "index.html",
    "/work-revenue/": ROOT / "work-revenue" / "index.html",
    "/nova-today/": ROOT / "nova-today" / "index.html",
    "/nova-create/": ROOT / "nova-create" / "index.html",
    "/car-hub/": ROOT / "car-hub" / "index.html",
    "/home-hub/": ROOT / "home-hub" / "index.html",
    "/signin/": ROOT / "signin" / "index.html",
    "/early-access/": ROOT / "early-access" / "index.html",
    "/health/": ROOT / "health" / "index.html",
    "/deliver/": ROOT / "deliver" / "index.html",
    "/lifesaver/": ROOT / "lifesaver" / "index.html",
    "/about/": ROOT / "about" / "index.html",
    "/contact/": ROOT / "contact" / "index.html",
    "/technologies/": ROOT / "technologies" / "index.html",
    "/technologies/autonomous-operations-agent/": ROOT / "technologies" / "autonomous-operations-agent" / "index.html",
    "/privacy/": ROOT / "privacy" / "index.html",
    "/terms/": ROOT / "terms" / "index.html",
    "/software-terms/": ROOT / "software-terms" / "index.html",
    "/accessibility/": ROOT / "accessibility" / "index.html",
}


def _html(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_pages_exist() -> None:
    for href, path in PAGES.items():
        assert path.is_file(), href


def test_home_presents_nova_and_work_revenue() -> None:
    home = _html(PAGES["/"])
    assert "AMICOR Nova" in home
    assert "AI for What’s Next." in home or "AI for What's Next." in home
    assert "Find work. Do work. Get paid." in home
    assert "Nova Work &amp; Revenue" in home
    assert 'href="/work-revenue/"' in home
    assert "Home Hub" in home
    assert "Car Hub" in home
    assert "Illustrative product interface" in home


def test_no_placeholder_or_admin_links() -> None:
    forbidden = ("href=\"#\"", "href='#'", "/platform-ops/", "/app/riders", "stripe.com/checkout")
    for href, path in PAGES.items():
        text = _html(path)
        for token in forbidden:
            assert token not in text, f"{href} contains {token}"


def test_nav_and_ctas_use_real_routes() -> None:
    home = _html(PAGES["/"])
    for href in ("/products/", "/solutions/", "/pricing/", "/resources/", "/about/", "/contact/", "/signin/", "/early-access/"):
        assert f'href="{href}"' in home
    assert "Watch Demo" in home
    assert "intent=demo" in home


def test_hardware_assets_exist() -> None:
    assert (ROOT / "assets" / "img" / "home-hub.svg").is_file()
    assert (ROOT / "assets" / "img" / "car-hub.svg").is_file()
    for name in ("card-work-revenue.svg", "card-nova-today.svg", "card-nova-create.svg", "card-delivery.svg", "card-lifesaver.svg"):
        assert (ROOT / "assets" / "img" / name).is_file(), name
    assert "See More. Care More. Be There." in _html(PAGES["/home-hub/"])
    assert "On the Road. On Your Team." in _html(PAGES["/car-hub/"])


def test_home_product_cards_have_meaningful_visuals() -> None:
    home = _html(PAGES["/"])
    for token in (
        "card-work-revenue.svg",
        "card-nova-today.svg",
        "card-nova-create.svg",
        "card-delivery.svg",
        "card-lifesaver.svg",
        "assets/img/home-hub.svg",
        "assets/img/car-hub.svg",
    ):
        assert token in home, token
    assert "card-visual today" not in home
    assert 'aria-label="Footer product links"' in home
    assert "class=\"footer-links\"" in home


def test_public_claim_safety() -> None:
    home = _html(PAGES["/"])
    lowered = home.lower()
    for token in ("fda approved", "10,000 customers", "certified hipaa", "emergency medical service"):
        assert token not in lowered
    assert "not a diagnostic product" in _html(PAGES["/lifesaver/"]).lower()


def test_sitemap_includes_new_routes() -> None:
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    for route in ("/work-revenue/", "/car-hub/", "/products/", "/signin/"):
        assert f"https://getamicor.com{route}" in sitemap


def main() -> None:
    tests = [
        test_required_pages_exist,
        test_home_presents_nova_and_work_revenue,
        test_no_placeholder_or_admin_links,
        test_nav_and_ctas_use_real_routes,
        test_hardware_assets_exist,
        test_home_product_cards_have_meaningful_visuals,
        test_public_claim_safety,
        test_sitemap_includes_new_routes,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"TESTS_PASSED={len(tests)}")


if __name__ == "__main__":
    main()
