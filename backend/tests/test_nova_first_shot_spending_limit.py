"""Financial guard regressions; all HTTP is intercepted, no paid requests."""
import io
import json
import urllib.error

import pytest

from app.core.nova.creative_studio import kling as module


@pytest.fixture
def provider(monkeypatch):
    for key, value in {'FAL_KEY': 'private-test-key', 'NOVA_CREATIVE_VIDEO_PROVIDER': 'kling',
                       'NOVA_CREATIVE_VIDEO_LIVE_ENABLED': 'true',
                       'NOVA_CREATIVE_KLING_LIVE_ENABLED': 'true'}.items():
        monkeypatch.setenv(key, value)
    return module.FalKlingVideoProvider()


def intercept(monkeypatch, pricing, *, pricing_error=False):
    calls = []
    class Response(io.BytesIO):
        pass
    class Opener:
        def open(self, req, **kwargs):
            calls.append(req)
            if req.full_url.startswith('https://api.fal.ai/'):
                if pricing_error:
                    raise urllib.error.HTTPError(req.full_url, 403, 'private-test-key', {}, None)
                return Response(json.dumps(pricing).encode())
            assert req.full_url == module.QUEUE + module.MODEL
            assert req.get_method() == 'POST'
            return Response(json.dumps({
                'request_id': 'request-1',
                'status_url': 'https://queue.fal.run/fal-ai/kling-video/requests/request-1/status',
                'response_url': 'https://queue.fal.run/fal-ai/kling-video/requests/request-1',
            }).encode())
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *a: Opener())
    return calls


def quote(**changes):
    return {'prices': [dict(endpoint_id=module.MODEL, unit_price='0.07',
                            unit='second', currency='USD', **changes)]}


def submit(provider, **changes):
    return provider.generate(brief=dict(prompt_image_url='data:image/png;base64,aGVsbG8=',
                                       controlled_first_shot=True, max_cost_usd=1,
                                       persist_task_before_poll=True, **changes))


def test_under_limit_submits_once_with_no_retry_or_fallback(provider, monkeypatch):
    calls = intercept(monkeypatch, quote())
    result = submit(provider)
    assert result['status'] == 'PROCESSING'
    assert [r.get_method() for r in calls] == ['GET', 'POST']
    post = calls[1]
    assert post.get_header('X-fal-no-retry') == '1'
    assert post.get_header('X-app-fal-disable-fallback') == 'true'
    assert json.loads(post.data)['duration'] == '5'
    assert result['submission_price_check']['checked_cost_usd'] == '0.35'
    assert result['submission_price_check']['provider_billing_guaranteed'] is False


@pytest.mark.parametrize('change', [
    {'unit_price': '0.21'}, {'unit_price': '0.200000000000000000000000000001'},
    {'unit_price': '1E999999999999999999'}, {'unit_price': 'NaN'}, {'unit_price': 'Infinity'},
    {'unit_price': '-0.01'}, {'unit_price': 0}, {'unit_price': True},
    {'unit': 'GPU second'}, {'currency': 'EUR'}, {'endpoint_id': 'different-model'},
])
def test_bad_or_over_limit_price_never_posts(provider, monkeypatch, change):
    pricing = quote()
    pricing['prices'][0].update(change)
    calls = intercept(monkeypatch, pricing)
    result = submit(provider)
    assert result['status'] == 'ERROR'
    assert not result['task_id']
    assert [r.get_method() for r in calls] == ['GET']


@pytest.mark.parametrize('pricing', [{}, {'prices': []}, {'prices': [None]},
                                    {'prices': 'invalid'}, {'prices': [{}, {}]}])
def test_malformed_pricing_never_posts(provider, monkeypatch, pricing):
    calls = intercept(monkeypatch, pricing)
    assert submit(provider)['status'] == 'ERROR'
    assert len(calls) == 1


def test_pricing_permission_failure_is_safe_and_does_not_post(provider, monkeypatch):
    calls = intercept(monkeypatch, quote(), pricing_error=True)
    result = submit(provider)
    assert result['status'] == 'ERROR'
    assert 'private-test-key' not in result['message']
    assert len(calls) == 1


@pytest.mark.parametrize('limit', [None, 0, -1, 1.01, 'NaN', 'Infinity', True])
def test_missing_or_invalid_limit_never_contacts_provider(provider, monkeypatch, limit):
    calls = intercept(monkeypatch, quote())
    result = provider.generate(brief={'prompt_image_url': 'data:image/png;base64,aGVsbG8=',
                                     'controlled_first_shot': True, 'max_cost_usd': limit})
    assert result['status'] == 'ERROR'
    assert calls == []


def test_exact_limit_allowed_without_float_rounding(provider, monkeypatch):
    pricing = quote()
    pricing['prices'][0]['unit_price'] = '0.20'
    calls = intercept(monkeypatch, pricing)
    assert submit(provider)['status'] == 'PROCESSING'
    assert len(calls) == 2


def test_existing_task_recovery_never_prices_or_submits_again(provider, monkeypatch):
    token = provider._encode_task({
        'request_id': 'request-1',
        'status_url': 'https://queue.fal.run/fal-ai/kling-video/requests/request-1/status',
        'response_url': 'https://queue.fal.run/fal-ai/kling-video/requests/request-1',
    })
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url))
        return {'status': 'COMPLETED', 'error': 'failed'}
    monkeypatch.setattr(provider, '_request_json', request)
    monkeypatch.setattr(provider, '_first_shot_price', lambda *a: pytest.fail('No fresh pricing during recovery'))
    result = provider.generate(brief={'resume_task_id': token, 'controlled_first_shot': True})
    assert result['status'] == 'ERROR'
    assert [method for method, url in calls] == ['GET']


@pytest.mark.parametrize('value', [None, 0, -1, 1.01, float('nan'), float('inf')])
def test_http_input_requires_finite_limit_within_one_dollar(value):
    from pydantic import ValidationError
    from app.core.nova.creative_studio.router import FirstShotSubmitIn
    body = {'confirm_paid_generation': True, 'reference_image_asset_id': 'image-1'}
    if value is not None:
        body['max_cost_usd'] = value
    with pytest.raises(ValidationError):
        FirstShotSubmitIn(**body)


def test_http_input_preserves_explicit_limit():
    from app.core.nova.creative_studio.router import FirstShotSubmitIn
    body = FirstShotSubmitIn(confirm_paid_generation=True, reference_image_asset_id='image-1', max_cost_usd=0.5)
    assert body.max_cost_usd == 0.5
