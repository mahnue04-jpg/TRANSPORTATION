"""Development-only first-customer funnel checks. Does not call production."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = (ROOT / "start" / "index.html").read_text(encoding="utf-8")
GUIDE = (ROOT / "guides" / "research-memo-setup" / "index.html").read_text(encoding="utf-8")
CONFIG = (ROOT / "assets" / "js" / "site-config.js").read_text(encoding="utf-8")
JS = (ROOT / "assets" / "js" / "site.js").read_text(encoding="utf-8")
SITEMAP = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
NAV_PAGES = [
    ROOT / "index.html",
    ROOT / "business-services" / "index.html",
    ROOT / "pricing" / "index.html",
]

PRICES = (
    "$0",
    "$49 one-time",
    "$99/month",
    "$299/month",
)


def test_funnel_uses_published_prices_and_stays_unlisted() -> None:
    for price in PRICES:
        assert price in START
    assert "as of October 5, 2026" in START
    assert "does not take payment" in START
    assert 'content="noindex,nofollow"' in START
    assert "data-start-funnel" in START
    assert "data-early-access-form" in START
    for label in (
        "Select Explore &amp; scope",
        "Select Starter Task",
        "Select Launch Operations",
        "Select Business Operations",
    ):
        assert label in START
    assert ">Select</button>" not in START
    product = START.split('name="product"', 1)[1].split("</select>", 1)[0]
    assert "Nova Operations Agent" in product
    assert "Business Services" not in product
    assert "Ask Nova" not in product
    assert "/start/" not in SITEMAP
    for page in NAV_PAGES:
        html = page.read_text(encoding="utf-8")
        assert 'href="/start/"' not in html


def test_funnel_flag_is_a_publish_gate() -> None:
    build = (ROOT / "scripts" / "build-production.mjs").read_text(encoding="utf-8")
    gate = (ROOT / "functions" / "_funnel-gate.js").read_text(encoding="utf-8")
    routes = (ROOT / "_routes.json").read_text(encoding="utf-8")
    assert "firstCustomerFunnel: false" in CONFIG
    assert "readFunnelPublished" in build
    assert "guides/research-memo-setup" in build
    assert "FIRST_CUSTOMER_FUNNEL_PUBLISHED = false" in gate
    assert 'AMICOR_FUNNEL_PREVIEW' in gate
    assert '"/api/*"' in routes
    assert '"/start"' in routes
    assert '"/start/*"' in routes
    assert "research-memo-setup" in routes
    assert 'content="noindex,nofollow"' in START


def test_funnel_posts_through_corrected_lead_capture() -> None:
    assert 'formEndpoint: "/api/leads"' in CONFIG
    assert "firstCustomerFunnel: false" in CONFIG
    assert 'affiliateEnrollment: "pending"' in CONFIG
    assert "data-selected-plan" in JS
    assert 'payload.message = "Starting option: "' in JS
    assert "result.referenceId" in JS
    assert "Email delivery was not confirmed." in JS
    assert "A notification email was sent." not in JS
    assert 'payload.product = "Nova Operations Agent"' in JS
    assert "aria-pressed" in JS


def test_guide_is_original_and_enrollment_pending() -> None:
    assert "Affiliate enrollment: pending" in GUIDE
    assert "no affiliate links" in GUIDE
    assert "no commission" in GUIDE
    assert "October 11, 2026" in GUIDE
    assert "amazon." not in GUIDE.lower()
    assert "shareasale" not in GUIDE.lower()
    assert "commission rate" not in GUIDE.lower()
    assert "$" not in GUIDE
    assert 'content="noindex,nofollow"' in GUIDE
    assert "/guides/" not in SITEMAP


def main() -> None:
    tests = [
        test_funnel_uses_published_prices_and_stays_unlisted,
        test_funnel_flag_is_a_publish_gate,
        test_funnel_posts_through_corrected_lead_capture,
        test_guide_is_original_and_enrollment_pending,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"FUNNEL_TESTS_PASSED={len(tests)}")


if __name__ == "__main__":
    main()
