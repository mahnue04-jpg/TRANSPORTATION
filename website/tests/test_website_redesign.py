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
    "/nova-operations/": ROOT / "nova-operations" / "index.html",
    "/nova-create/": ROOT / "nova-create" / "index.html",
    "/nova-snap/": ROOT / "nova-snap" / "index.html",
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
    import sys

    sys.path.insert(0, str(ROOT))
    from catalog import PRODUCTS

    home = _html(PAGES["/"])
    assert home.count("product-visual-card") == 12
    assert 'id="home-product-catalog"' in home
    assert "These are business services, not catalog products." in home
    assert 'data-listing="service"' in home
    assert "home-product-stage" not in home
    assert ">Available<" not in home
    for product in PRODUCTS:
        marker = f'data-product-id="{product["id"]}"'
        assert home.count(marker) == 1, product["id"]
        assert f'src="assets/img/{product["art"]}"' in home
        assert (ROOT / "assets" / "img" / product["art"]).is_file()
        assert f'<p class="product-visual-status">{product["status"]}</p>' in home
    assert 'src="../assets/img/' not in home
    assert 'href="/products/"' in home
    assert "Join waitlist" in home
    assert "Nova Snap" in home
    snap = next(product for product in PRODUCTS if product["id"] == "nova-snap")
    assert snap["status"] == "Coming Soon"
    assert "calling is not available" in home.lower() or "Live calling is not available." in home


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


def test_product_catalog_uses_distinct_images() -> None:
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
    assert len(parser.pairs) == 12
    srcs = [src for src, _alt in parser.pairs]
    alts = [alt for _src, alt in parser.pairs]
    assert len(set(srcs)) == 12
    assert len(set(alts)) == 12
    hashes = []
    for src, alt in parser.pairs:
        path = (ROOT / "products" / src).resolve()
        assert path.is_file(), src
        assert len(alt) > 24, alt
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    assert len(set(hashes)) == 12
    for src, _alt in parser.pairs:
        path = (ROOT / "products" / src).resolve()
        if src.endswith(".jpg"):
            assert path.stat().st_size > 40_000, src
            assert path.read_bytes()[:3] == b"\xff\xd8\xff"
        elif src.endswith(".svg"):
            assert path.stat().st_size > 100, src
            assert b"<svg" in path.read_bytes(), src
        else:
            raise AssertionError(f"Unexpected image type: {src}")
    assert 'type="file"' not in html
    assert "public submissions disabled" in html.lower()
    assert 'href="/early-access/?product=Nova%20Casting%20%26%20Auditions"' in html
    assert "Nova%20Casting%20and%20Auditions" not in html
    assert "\\n              <tr><td>Nova Creative Studio" not in html
    assert "card-home-hub.jpg" in html
    assert "card-farm-app.svg" in html
    assert "AMICOR Health" in html
    assert 'src="../assets/img/card-health.jpg"' in html
    assert "No public rides and no licensed-market claim." in html
    assert "Connected-care concept, not an emergency service or medical device." in html
    assert "card-lifesaver.jpg" in html
    health = _html(PAGES["/health/"])
    assert "does not claim that AMICOR currently holds a local operating license" in health
    assert "not a diagnostic product" in _html(PAGES["/lifesaver/"]).lower()
    visuals = (ROOT / "assets" / "css" / "product-visuals.css").read_text(encoding="utf-8")
    assert ".product-visual-art{position:relative;height:200px;overflow:hidden" in visuals
    home = _html(PAGES["/"])
    assert "Health &amp; Deliver" not in home
    assert "Health & Deliver" not in home
    assert 'href="/health/"' in home
    assert ">AMICOR Health</h3>" in html
    assert "Conceptual illustrations." in html
    assert 'src="../assets/img/card-home-hub.jpg"' in _html(PAGES["/home-hub/"])
    assert 'AMICOR Farm App' in _html(PAGES["/car-hub/"])


def test_hardware_assets_exist() -> None:
    for name in ("card-home-hub.jpg", "card-car-hub.jpg", "card-work-revenue.jpg", "card-nova-today.jpg", "card-nova-create.jpg", "card-delivery.jpg", "card-lifesaver.jpg"):
        path = ROOT / "assets" / "img" / name
        assert path.is_file(), name
        assert path.stat().st_size > 40_000, name
    assert "See More. Care More. Be There." in _html(PAGES["/home-hub/"])
    assert "AMICOR Farm App" in _html(PAGES["/car-hub/"])


def test_customer_paths_and_price_consistency() -> None:
    login = _html(PAGES["/signin/"])
    assert 'href="https://amicor-health-isf-py.onrender.com/nova?signin=1"' in login
    for path in (PAGES["/pricing/"], PAGES["/nova-operations/"]):
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
    assert "product.value = requestedProduct" in site_js
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


def test_one_catalog_card_per_product() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from catalog import PRODUCTS

    cards_by_id: dict[str, list[str]] = {product["id"]: [] for product in PRODUCTS}
    visual_outside = []
    for path in ROOT.rglob("*.html"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        if "product-visual-card" in text and rel not in {"products/index.html", "index.html"}:
            visual_outside.append(rel)
        for product in PRODUCTS:
            marker = f'data-product-id="{product["id"]}"'
            cards_by_id[product["id"]].extend([rel] * text.count(marker))
    assert visual_outside == []
    for product_id, hits in cards_by_id.items():
        assert sorted(hits) == ["index.html", "products/index.html"], (product_id, hits)
    home = _html(PAGES["/"])
    tech = _html(PAGES["/technologies/"])
    resources = _html(PAGES["/resources/"])
    for product in PRODUCTS:
        name = f"<h3>{product['name'].replace('&', '&amp;')}</h3>"
        assert home.count(name) == 1
        assert name not in tech
        assert name not in resources
    assert "Home Hub &amp; Car Hub" not in home
    assert "<h1>Nova Create</h1>" not in _html(PAGES["/nova-create/"])
    assert "<h3>AMICOR Nova Create</h3>" not in _html(PAGES["/products/"])
    assert "<h1>Nova Creative Studio</h1>" in _html(PAGES["/nova-create/"])
    snap = _html(PAGES["/nova-snap/"])
    assert "<h1>Nova Snap</h1>" in snap
    assert "Nova Snap is not Synapse Meeting." in snap
    assert "Live phone calling and video calling are not available." in snap
    assert "External email send is disabled." in snap
    assert "https://amicor-health-isf-py.onrender.com/nova/communications" in snap
    assert 'href="/nova-snap/"' in home
    nav = home.split('<nav id="site-nav"', 1)[1].split("</nav>", 1)[0]
    footer = home.split("<footer", 1)[1]
    assert nav.count('href="/nova-snap/"') == 1
    assert footer.count('href="/nova-snap/"') == 1
    early = _html(PAGES["/early-access/"])
    assert "<option>Nova Snap</option>" in early
    assert "<option>AMICOR Nova Create</option>" not in early
    assert "<option>Autonomous Operations Agent</option>" not in early
    assert 'label="Business services"' in early
    assert 'label="Products"' in early
    moved = _html(PAGES["/technologies/autonomous-operations-agent/"])
    assert "Not a separate product." in moved
    assert "$49" not in moved


def test_sitemap_includes_new_routes() -> None:
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    for route in ("/work-revenue/", "/car-hub/", "/products/", "/signin/", "/nova-snap/"):
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
        test_product_catalog_uses_distinct_images,
        test_one_catalog_card_per_product,
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
