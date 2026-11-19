"""Offline validation of both Cloudflare lead-key formats (no KV access)."""
from app.core.nova.growth_agent.website_inquiry_records import normalize_website_inquiry, normalize_inquiry_entries

OLD = "lead:2026-11-14T21:00:00.000Z:12345678-1234-1234-1234-123456789abc"
NEW = "lead:AMQ-AB12CD34"
RECORD = {
    "receivedAt": "2026-11-14T21:00:00Z",
    "name": "AMICOR QA Test",
    "company": "Fictional Company",
    "email": "qa@example.invalid",
    "product": "Business Services",
    "message": "INTERNAL TEST ONLY",
    "consent": True,
}


def test_legacy_key_normalization():
    row = normalize_website_inquiry(OLD, RECORD, trusted_synthetic_fixture=True)
    assert row is not None
    assert row["source_key"] == OLD
    assert row["is_synthetic"] is True


def test_reference_key_normalization():
    row = normalize_website_inquiry(NEW, {**RECORD, "referenceId": "AMQ-AB12CD34"})
    assert row is not None
    assert row["reference_id"] == "AMQ-AB12CD34"


def test_customer_message_cannot_mark_real_lead_synthetic():
    row = normalize_website_inquiry(NEW, RECORD)
    assert row is not None
    assert row["is_synthetic"] is False


def test_mismatched_reference_and_invalid_consent_fail_closed():
    assert normalize_website_inquiry(NEW, {**RECORD, "referenceId": "AMQ-ZZ99ZZ99"}) is None
    assert normalize_website_inquiry(NEW, {**RECORD, "consent": False}) is None


def test_dedupe_index_ignored_and_repeated_key_deduped():
    entries = [
        {"key": "dedupe:untrusted", "value": RECORD},
        {"key": NEW, "value": RECORD},
        {"key": NEW, "value": RECORD},
    ]
    assert len(normalize_inquiry_entries(entries)) == 1


def test_malformed_or_missing_source_rejected():
    assert normalize_website_inquiry(NEW, {"name": "Incomplete"}) is None
    try:
        normalize_inquiry_entries(None)
    except ValueError:
        pass
    else:
        raise AssertionError("Unavailable source cannot look like empty list")
