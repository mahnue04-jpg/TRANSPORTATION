"""Offline regression checks: no secrets, network, production writes or real leads."""
import io
import json
from unittest.mock import patch

import pytest

from app.core.nova.growth_agent.website_inquiry_cloudflare_readonly import (
    CloudflareReadonlyKV, staging_cloudflare_source_for_org,
)
from app.core.nova.growth_agent.website_inquiry_readonly import WebsiteInquirySourceError

ACCOUNT = "a" * 32
NAMESPACE = "b" * 32


class FakeResponse:
    def __init__(self, body):
        self._buffer = io.BytesIO(body)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, amount):
        return self._buffer.read(amount)


@pytest.mark.parametrize("environment,enabled", [
    ("production", "true"), ("staging", "false"), ("test", "true"),
])
def test_staging_gate_rejects_non_staging_or_disabled(monkeypatch, environment, enabled):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", environment)
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_KV_READ_ENABLED", enabled)
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_ORG_ID", "amicor")
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_CF_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_CF_NAMESPACE_ID", NAMESPACE)
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_CF_READ_TOKEN", "synthetic-test-token")
    assert staging_cloudflare_source_for_org("amicor") is None


def test_staging_gate_requires_exact_trusted_tenant_and_token(monkeypatch):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_KV_READ_ENABLED", "true")
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_ORG_ID", "amicor")
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_CF_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_CF_NAMESPACE_ID", NAMESPACE)
    monkeypatch.delenv("NOVA_WEBSITE_INQUIRY_CF_READ_TOKEN", raising=False)
    assert staging_cloudflare_source_for_org("amicor") is None
    monkeypatch.setenv("NOVA_WEBSITE_INQUIRY_CF_READ_TOKEN", "synthetic-test-token")
    assert staging_cloudflare_source_for_org("other-tenant") is None
    assert isinstance(staging_cloudflare_source_for_org("amicor"), CloudflareReadonlyKV)


def test_transport_uses_only_get_and_prefix(monkeypatch):
    source = CloudflareReadonlyKV(account_id=ACCOUNT, namespace_id=NAMESPACE, token="fake")
    requests = []
    def fake_urlopen(request, timeout):
        requests.append(request)
        if "/keys?" in request.full_url:
            return FakeResponse(json.dumps({
                "success": True,
                "result": [{"name": "lead:2026-11-15T03:31:55.384Z:fixture"}],
                "result_info": {"cursor": None},
            }).encode())
        return FakeResponse(b'{"receivedAt":"2026-11-15T03:31:55.384Z","consent":true}')
    with patch("app.core.nova.growth_agent.website_inquiry_cloudflare_readonly.urlopen", fake_urlopen):
        listing = source.list_keys(prefix="lead:", cursor=None)
        value = source.get_text(listing["keys"][0]["name"])
    assert listing["list_complete"] is True
    assert json.loads(value)["consent"] is True
    assert len(requests) == 2
    assert all(request.get_method() == "GET" for request in requests)
    assert "prefix=lead%3A" in requests[0].full_url
    assert all("fake" not in request.full_url for request in requests)


def test_transport_fails_closed_on_provider_failure():
    source = CloudflareReadonlyKV(account_id=ACCOUNT, namespace_id=NAMESPACE, token="fake")
    with patch(
        "app.core.nova.growth_agent.website_inquiry_cloudflare_readonly.urlopen",
        side_effect=RuntimeError("private provider details"),
    ):
        with pytest.raises(WebsiteInquirySourceError) as exc:
            source.list_keys(prefix="lead:", cursor=None)
    assert "private provider details" not in str(exc.value)


def test_transport_rejects_invalid_key():
    source = CloudflareReadonlyKV(account_id=ACCOUNT, namespace_id=NAMESPACE, token="fake")
    with pytest.raises(WebsiteInquirySourceError):
        source.get_text("dedupe:customer")
