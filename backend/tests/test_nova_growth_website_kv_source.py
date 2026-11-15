"""Pure synthetic tests. Never query Cloudflare or real customer records."""
import pytest
from urllib.parse import unquote

from app.core.nova.growth_agent.website_kv_source import (
    WebsiteKVSource, configured_website_source,
)


def _record(**changes):
    record = {
        "receivedAt": "2026-11-14T12:00:00Z",
        "name": "Synthetic Owner Inquiry",
        "email": "SAMPLE@example.invalid",
        "company": "Example LLC",
        "product": "Nova Operations Agent",
        "message": "CSV formatting",
        "consent": True,
        "is_synthetic": True,
    }
    record.update(changes)
    return record


def _source(pages, records, *, tenant="tenant-one"):
    def fake_request(path):
        if path.startswith("keys?"):
            return pages.pop(0)
        if path.startswith("values/"):
            return records.get(unquote(path.removeprefix("values/")))
        raise AssertionError("unexpected read")
    return WebsiteKVSource(
        tenant_id=tenant, account_id="account1234", namespace_id="namespace1234",
        token="synthetic-token", request_json=fake_request,
    )


def _complete(*keys):
    return {"success": True, "result": [{"name": key} for key in keys],
            "result_info": {}}


def test_default_off_does_not_construct_connector(monkeypatch):
    monkeypatch.delenv("NOVA_GA_WEBSITE_KV_READ_ENABLED", raising=False)
    assert configured_website_source() is None


def test_flag_without_credentials_fails_closed(monkeypatch):
    monkeypatch.setenv("NOVA_GA_WEBSITE_KV_READ_ENABLED", "true")
    for key in ("NOVA_GA_WEBSITE_KV_TENANT_ID", "NOVA_GA_WEBSITE_CF_ACCOUNT_ID",
                "NOVA_GA_WEBSITE_CF_NAMESPACE_ID", "NOVA_GA_WEBSITE_CF_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert configured_website_source() is None


def test_legacy_and_amq_source_records_are_distinct_and_synthetic():
    old = "lead:2026-11-14T12:00:00Z:abcd"
    new = "lead:AMQ-TEST123"
    src = _source([_complete(old, new)], {old: _record(), new: _record()})
    result = src.read("tenant-one")
    assert result["state"] == "available"
    assert result["complete"] is True
    assert len(result["inquiries"]) == 2
    assert result["inquiries"][0]["email"] == "sample@example.invalid"
    assert result["inquiries"][1]["reference_id"] == "AMQ-TEST123"
    assert all(x["is_synthetic"] for x in result["inquiries"])


def test_tenant_mismatch_denied_before_request():
    src = _source([_complete()], {})
    with pytest.raises(PermissionError):
        src.read("different-tenant")


def test_invalid_record_and_dedupe_key_not_included():
    good = "lead:AMQ-TEST"
    bad = "lead:AMQ-INVALID"
    src = _source([_complete(good, good, bad, "dedupe:not-a-lead")],
                  {good: _record(), bad: _record(email="bad")})
    result = src.read("tenant-one")
    assert result["state"] == "available"
    assert [x["source_key"] for x in result["inquiries"]] == [good]


def test_disconnected_or_failed_api_returns_unavailable_not_zero_ready():
    def failing(_path):
        raise ValueError("private-token-must-not-leak")
    src = WebsiteKVSource(tenant_id="tenant-one", account_id="account1234",
                          namespace_id="namespace1234", token="secret",
                          request_json=failing)
    result = src.read("tenant-one")
    assert result == {"state": "unavailable", "inquiries": [], "complete": False}
    assert "private-token" not in str(result)


def test_partial_pagination_never_discloses_partial_records():
    k = "lead:AMQ-TEST"
    pages = [{"success": True, "result": [{"name": k}],
              "result_info": {"cursor": "still-more"}} for _ in range(4)]
    src = _source(pages, {k: _record()})
    result = src.read("tenant-one")
    assert result == {"state": "stale", "inquiries": [], "complete": False}


def test_repeated_cursor_fails_closed():
    pages = [{"success": True, "result": [], "result_info": {"cursor": "dup"}},
             {"success": True, "result": [], "result_info": {"cursor": "dup"}}]
    src = _source(pages, {})
    result = src.read("tenant-one")
    assert result["state"] == "stale"
    assert result["inquiries"] == []


def test_failed_kv_listing_fails_closed():
    src = _source([{"success": False, "result": [], "result_info": {}}], {})
    assert src.read("tenant-one")["state"] == "unavailable"


def test_explicit_value_api_error_never_looks_like_zero_customers():
    key = "lead:AMQ-SAMPLE"
    src = _source([_complete(key)], {
        key: {"success": False, "errors": [{"message": "private error"}]}
    })
    assert src.read("tenant-one") == {
        "state": "unavailable", "inquiries": [], "complete": False
    }
