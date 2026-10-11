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
    assert "/start/" not in SITEMAP
    for page in NAV_PAGES:
        html = page.read_text(encoding="utf-8")
        assert 'href="/start/"' not in html


def test_funnel_posts_through_corrected_lead_capture() -> None:
    assert 'formEndpoint: "/api/leads"' in CONFIG
    assert "firstCustomerFunnel: false" in CONFIG
    assert 'affiliateEnrollment: "pending"' in CONFIG
    assert "data-selected-plan" in JS
    assert 'payload.message = "Starting option: "' in JS
    assert "result.referenceId" in JS
    assert "Email delivery was not confirmed." in JS


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
        test_funnel_posts_through_corrected_lead_capture,
        test_guide_is_original_and_enrollment_pending,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"FUNNEL_TESTS_PASSED={len(tests)}")


if __name__ == "__main__":
    main()
