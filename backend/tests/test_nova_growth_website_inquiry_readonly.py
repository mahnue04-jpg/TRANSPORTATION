"""Offline proof that lead listing is bounded, read-only, and fail-closed."""
import json

import pytest

from app.core.nova.growth_agent.website_inquiry_readonly import (
    WebsiteInquirySourceError,
    read_website_inquiries,
)

K1 = "lead:AMQ-AB12CD34"
K2 = "lead:AMQ-AB12CD35"
RECORD = {
    "receivedAt": "2026-11-14T21:00:00Z",
    "name": "Synthetic QA",
    "company": "Fictional Co",
    "email": "qa@example.invalid",
    "message": "INTERNAL TEST ONLY",
    "consent": True,
}


class Fixture:
    def __init__(self, pages, records=None):
        self.pages = pages
        self.records = records or {K1: json.dumps(RECORD), K2: json.dumps(RECORD)}
        self.list_calls = []
        self.get_calls = []

    def list_keys(self, *, prefix, cursor):
        assert prefix == "lead:"
        self.list_calls.append(cursor)
        return self.pages[cursor]

    def get_text(self, key):
        self.get_calls.append(key)
        return self.records.get(key)


def test_reads_complete_paginated_fixture_and_deduplicates():
    source = Fixture({
        None: {"keys": [{"name": K1}], "list_complete": False, "cursor": "next"},
        "next": {"keys": [{"name": K1}, {"name": K2}], "list_complete": True},
    })
    result = read_website_inquiries(source, trusted_synthetic_fixture=True)
    assert len(result) == 2
    assert all(item["is_synthetic"] for item in result)
    assert source.get_calls == [K1, K2]


def test_customer_synthetic_words_do_not_mark_untrusted_record():
    source = Fixture({None: {"keys": [{"name": K1}], "list_complete": True}})
    assert read_website_inquiries(source)[0]["is_synthetic"] is False


@pytest.mark.parametrize("pages", [
    {None: {"keys": [], "list_complete": False}},
    {None: {"keys": [], "list_complete": False, "cursor": "repeat"},
     "repeat": {"keys": [], "list_complete": False, "cursor": "repeat"}},
    {None: {"keys": [], "list_complete": "false"}},
    {None: {"keys": "not-a-list", "list_complete": True}},
])
def test_incomplete_invalid_or_cyclic_listing_fails_closed(pages):
    with pytest.raises(WebsiteInquirySourceError):
        read_website_inquiries(Fixture(pages))


def test_missing_key_cannot_be_reported_as_zero():
    source = Fixture({None: {"keys": [{"name": K1}], "list_complete": True}}, records={K2: json.dumps(RECORD)})
    with pytest.raises(WebsiteInquirySourceError):
        read_website_inquiries(source)


def test_too_large_record_cannot_leak():
    source = Fixture({None: {"keys": [{"name": K1}], "list_complete": True}}, records={K1: "X" * 20000})
    with pytest.raises(WebsiteInquirySourceError) as error:
        read_website_inquiries(source)
    assert "X" not in str(error.value)


def test_provider_error_cannot_leak_sensitive_contents():
    class Broken:
        def list_keys(self, **kwargs):
            raise RuntimeError("SECRET CUSTOMER DATA")
    with pytest.raises(WebsiteInquirySourceError) as error:
        read_website_inquiries(Broken())
    assert "SECRET" not in str(error.value)


def test_ignores_non_lead_keys_without_fetch():
    source = Fixture({None: {"keys": [{"name": "dedupe:123"}, {"name": K1}], "list_complete": True}})
    assert len(read_website_inquiries(source)) == 1
    assert source.get_calls == [K1]
