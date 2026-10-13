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


def test_homepage_renders_product_illustrations() -> None:
    home = _html(PAGES["/"])
    assert "Product illustrations" in home
    assert 'class="product-visual-grid"' in home
    for name in (
        "card-operations.jpg",
        "card-work-revenue.jpg",
        "card-nova-create.jpg",
        "card-casting.jpg",
        "card-ask-nova.jpg",
        "card-nova-today.jpg",
        "card-lifesaver.jpg",
        "card-home-hub.jpg",
        "card-car-hub.jpg",
        "card-delivery.jpg",
        "card-research.jpg",
        "card-data.jpg",
        "card-crm.jpg",
        "card-health.jpg",
        "card-hubs.jpg",
    ):
        assert f'src="assets/img/{name}"' in home, name
        assert (ROOT / "assets" / "img" / name).is_file(), name
    assert 'src="../assets/img/' not in home


def test_home_presents_services_and_nova() -> None:
    home = _html(PAGES["/"])
    assert 'href="/business-services/"' in home
    for route in ("/ask-nova/", "/nova-operations/", "/nova-create/", "/samples/"):
        assert f'href="{route}"' in home
    assert "human review" in home.lower()
    assert "fictional" in home.lower()
    assert "Future AMICOR initiatives" in home


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
    assert "Run the Interactive Demo" in home
    assert "https://amicor-health-isf-py.onrender.com/nova/anonymous-agent" in home


def test_product_catalog_uses_ten_distinct_images() -> None:
    import hashlib
    from html.parser import HTMLParser

    class Cards(HTMLParser):
        def __init__(self):
            super().__init__()
            self.pairs = []
            self._card = False
            self._depth = 0

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "article" and "product-visual-card" in values.get("class", ""):
                self._card = True
                self._depth = 1
            elif self._card:
                self._depth += 1
                if tag == "img":
                    self.pairs.append((values.get("src", ""), values.get("alt", "")))

        def handle_endtag(self, tag):
            if self._card:
                self._depth -= 1
                if self._depth <= 0:
                    self._card = False

    html = _html(PAGES["/products/"])
    parser = Cards()
    parser.feed(html)
    assert len(parser.pairs) == 10
    srcs = [src for src, _alt in parser.pairs]
    alts = [alt for _src, alt in parser.pairs]
    assert len(set(srcs)) == 10
    assert len(set(alts)) == 10
    hashes = []
    for src, alt in parser.pairs:
        path = (ROOT / "products" / src).resolve()
        assert path.is_file(), src
        assert len(alt) > 24, alt
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    assert len(set(hashes)) == 10
    for src, _alt in parser.pairs:
        path = (ROOT / "products" / src).resolve()
        assert src.endswith(".jpg"), src
        assert path.stat().st_size > 40_000, src
        assert path.read_bytes()[:3] == b"\xff\xd8\xff"
    assert 'type="file"' not in html
    assert "public submissions disabled" in html.lower()
    assert 'href="/early-access/?product=Nova%20Casting%20%26%20Auditions"' in html
    assert "Nova%20Casting%20and%20Auditions" not in html
    assert "\\n              <tr><td>Nova Creative Studio" not in html
    assert "card-home-hub.jpg" in html
    assert "card-car-hub.jpg" in html
    assert "Conceptual illustrations." in html
    assert 'src="../assets/img/card-home-hub.jpg"' in _html(PAGES["/home-hub/"])
    assert 'src="../assets/img/card-car-hub.jpg"' in _html(PAGES["/car-hub/"])


def test_hardware_assets_exist() -> None:
    for name in ("card-home-hub.jpg", "card-car-hub.jpg", "card-work-revenue.jpg", "card-nova-today.jpg", "card-nova-create.jpg", "card-delivery.jpg", "card-lifesaver.jpg"):
        path = ROOT / "assets" / "img" / name
        assert path.is_file(), name
        assert path.stat().st_size > 40_000, name
    assert "See More. Care More. Be There." in _html(PAGES["/home-hub/"])
    assert "On the Road. On Your Team." in _html(PAGES["/car-hub/"])


def test_customer_paths_and_price_consistency() -> None:
    login = _html(PAGES["/signin/"])
    assert 'href="https://amicor-health-isf-py.onrender.com/nova?signin=1"' in login
    for path in (PAGES["/pricing/"], PAGES["/technologies/autonomous-operations-agent/"]):
        text = _html(path)
        for price in ("$49", "$99/month", "$299/month"):
            assert price in text
        assert "$29/month" not in text
        assert "does not collect payment" in text
    assert "class=\"footer-links\"" in _html(PAGES["/"])


def test_public_claim_safety() -> None:
    home = _html(PAGES["/"])
    lowered = home.lower()
    for token in ("fda approved", "10,000 customers", "certified hipaa", "emergency medical service"):
        assert token not in lowered
    assert "not a diagnostic product" in _html(PAGES["/lifesaver/"]).lower()


def test_casting_ctas_use_the_canonical_product() -> None:
    from urllib.parse import parse_qs, unquote

    canonical = "Nova Casting & Auditions"
    href = "/early-access/?product=Nova%20Casting%20%26%20Auditions"
    assert parse_qs(href.split("?", 1)[1])["product"] == [canonical]
    assert unquote(href.split("product=", 1)[1]) == canonical
    leads = (ROOT / "functions" / "api" / "leads.js").read_text(encoding="utf-8")
    assert f'"{canonical}"' in leads
    early = _html(PAGES["/early-access/"])
    assert "<option>Nova Casting &amp; Auditions</option>" in early
    site_js = (ROOT / "assets" / "js" / "site.js").read_text(encoding="utf-8")
    assert 'product.value = params.get("product")' in site_js
    wrong = "Nova%20Casting%20and%20Auditions"
    for path in ROOT.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert wrong not in text, path.relative_to(ROOT)
        for match in re.findall(r'href="([^"]*product=[^"]*Casting[^"]*)"', text):
            assert parse_qs(match.split("?", 1)[1])["product"] == [canonical], match
    not_found = (ROOT / "404.html").read_text(encoding="utf-8")
    assert 'content="noindex, nofollow"' in not_found
    assert 'href="/assets/css/site.css"' in not_found
    assert 'href="assets/css/site.css"' not in not_found


def test_sitemap_includes_new_routes() -> None:
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    for route in ("/work-revenue/", "/car-hub/", "/products/", "/signin/"):
        assert f"https://getamicor.com{route}" in sitemap


def main() -> None:
    tests = [
        test_required_pages_exist,
        test_homepage_renders_product_illustrations,
        test_home_presents_services_and_nova,
        test_no_placeholder_or_admin_links,
        test_nav_and_ctas_use_real_routes,
        test_hardware_assets_exist,
        test_customer_paths_and_price_consistency,
        test_product_catalog_uses_ten_distinct_images,
        test_casting_ctas_use_the_canonical_product,
        test_public_claim_safety,
        test_sitemap_includes_new_routes,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"TESTS_PASSED={len(tests)}")


if __name__ == "__main__":
    main()
