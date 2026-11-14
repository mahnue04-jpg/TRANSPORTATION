"""Offline regression tests: no real provider requests, credentials or charges."""
import io
import json
import urllib.error

import pytest

from app.core.nova.creative_studio import fal_diagnostic as mod


def response(prices):
    return {"prices": prices}


def price(unit="second", unit_price="0.07", currency="USD", endpoint_id=None):
    return {"endpoint_id": endpoint_id or mod.MODEL, "unit": unit,
            "unit_price": unit_price, "currency": currency}


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "private-test-credential")
    calls = []

    class Opener:
        def __init__(self, data=None, code=None):
            self.data, self.code = data, code

        def open(self, request, **kwargs):
            calls.append((request.get_method(), request.full_url, kwargs))
            assert request.get_method() == "GET"
            assert request.full_url.startswith("https://api.fal.ai/v1/models/pricing?")
            if self.code:
                raise urllib.error.HTTPError(request.full_url, self.code, "private-test-credential", {}, None)
            return io.BytesIO(json.dumps(self.data).encode())

    def invoke(data=None, code=None):
        monkeypatch.setattr(mod.urllib.request, "build_opener", lambda *args: Opener(data, code))
        return mod.fal_first_shot_diagnostic()

    return invoke, calls


def test_success_is_read_only_and_does_not_claim_submission_permission(probe):
    run, calls = probe
    report = run(response([price()]))
    assert report["key_authenticated"] == "PRICING_API_ACCEPTED"
    assert report["price_status"] == "VERIFIED_FOR_PRICING_API"
    assert report["price_usd_five_seconds"] == "0.35"
    assert report["account_balance"] == report["model_authorized"] == "UNVERIFIED"
    assert report["provider_request_submitted"] is False
    assert report["generation_enabled_by_this_check"] is False
    assert len(calls) == 1 and calls[0][0] == "GET"
    assert "private-test-credential" not in json.dumps(report)


@pytest.mark.parametrize("code,blocker", [
    (401, "FAL_AUTH_REJECTED"),
    (402, "FAL_ACCOUNT_PAYMENT_REQUIRED"),
    (403, "FAL_ACCESS_DENIED"),
    (302, "FAL_PRICING_HTTP_ERROR"),
    (500, "FAL_PRICING_HTTP_ERROR"),
])
def test_http_failure_fails_closed(probe, code, blocker):
    run, calls = probe
    report = run(code=code)
    assert blocker in report["blockers"]
    assert report["price_usd_five_seconds"] is None
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [
    {}, {"prices": []}, {"prices": [price(), price()]},
    {"prices": [price(currency="EUR")]},
    {"prices": [price(unit="GPU second")]},
    {"prices": [price(unit_price="NaN")]},
    {"prices": [price(unit_price="-1")]},
    {"prices": [price(endpoint_id="other-model")]},
    {"prices": [None]},
    {"prices": [price()], "has_more": True},
])
def test_bad_pricing_is_unverified(probe, payload):
    run, _ = probe
    report = run(payload)
    assert report["price_status"] == "UNVERIFIED"
    assert report["price_usd_five_seconds"] is None


def test_missing_key_never_contacts_provider(probe, monkeypatch):
    run, calls = probe
    monkeypatch.delenv("FAL_KEY")
    report = run(response([price()]))
    assert report["blockers"] == ["FAL_KEY_MISSING"]
    assert calls == []


def test_malformed_json_and_oversized_body_fail_closed(probe, monkeypatch):
    run, calls = probe

    class Opener:
        def __init__(self, body):
            self.body = body

        def open(self, request, **kwargs):
            calls.append((request.get_method(), request.full_url, kwargs))
            return io.BytesIO(self.body)

    for raw, blocker in [(b"not-json", "FAL_PRICING_UNAVAILABLE"),
                         (b"x" * 65537, "PRICING_RESPONSE_TOO_LARGE")]:
        monkeypatch.setattr(mod.urllib.request, "build_opener", lambda *a: Opener(raw))
        report = mod.fal_first_shot_diagnostic()
        assert blocker in report["blockers"]
        assert "private-test-credential" not in json.dumps(report)


def test_timeout_is_unverified(probe, monkeypatch):
    run, _ = probe

    class TimeoutOpener:
        def open(self, request, **kwargs):
            assert request.get_method() == "GET"
            raise TimeoutError("private-test-credential")

    monkeypatch.setattr(mod.urllib.request, "build_opener", lambda *a: TimeoutOpener())
    report = mod.fal_first_shot_diagnostic()
    assert "FAL_PRICING_UNAVAILABLE" in report["blockers"]
    assert "private-test-credential" not in json.dumps(report)


def test_redirect_handler_refuses_redirect():
    from app.core.nova.creative_studio.kling import _NoRedirect
    assert _NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid") is None


def test_boolean_and_over_precise_price_fail_closed(probe):
    run, _ = probe
    for value in [True, None, "Infinity", "0", "-0.01"]:
        report = run(response([price(unit_price=value)]))
        assert report["price_usd_five_seconds"] is None


def test_nonmatching_model_and_unknown_unit_are_never_authorized(probe):
    run, _ = probe
    for item in [price(endpoint_id="fal-ai/unapproved/model"), price(unit="requests")]:
        report = run(response([item]))
        assert report["model_authorized"] == "UNVERIFIED"
        assert report["price_status"] == "UNVERIFIED"
        assert not report["provider_request_submitted"]
