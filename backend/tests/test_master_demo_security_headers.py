from types import SimpleNamespace

import pytest

from app.middleware import SecurityHeadersMiddleware


@pytest.mark.parametrize(
    "path",
    [
        "/nova",
        "/nova/",
        "/nova/today",
        "/nova/workspace",
        "/nova/anonymous-operations",
        "/nova/work",
        "/nova/communications",
        "/nova/government",
        "/nova/business",
        "/nova/accounting",
        "/nova/accounting/aging",
        "/nova/accounting/trends",
        "/nova/creative",
    ],
)
@pytest.mark.asyncio
async def test_master_demo_routes_allow_same_origin_framing(path):
    middleware = SecurityHeadersMiddleware(app=lambda scope, receive, send: None)

    class Response:
        def __init__(self):
            self.headers = {}

    async def call_next(request):
        return Response()

    request = SimpleNamespace(url=SimpleNamespace(path=path))
    response = await middleware.dispatch(request, call_next)

    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]


@pytest.mark.asyncio
async def test_non_demo_routes_keep_deny_framing():
    middleware = SecurityHeadersMiddleware(app=lambda scope, receive, send: None)

    class Response:
        def __init__(self):
            self.headers = {}

    async def call_next(request):
        return Response()

    request = SimpleNamespace(url=SimpleNamespace(path="/dispatch"))
    response = await middleware.dispatch(request, call_next)

    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


@pytest.mark.parametrize('path', ['/nova/workspace', '/nova/workspace/'])
@pytest.mark.asyncio
async def test_workspace_generated_audio_allowed_without_remote_media_or_script_sources(path):
    middleware = SecurityHeadersMiddleware(app=lambda scope, receive, send: None)

    async def call_next(request):
        return SimpleNamespace(headers={})

    response = await middleware.dispatch(SimpleNamespace(url=SimpleNamespace(path=path)), call_next)
    policy = response.headers['Content-Security-Policy']
    assert "media-src 'self' blob:;" in policy
    assert "script-src 'self' 'unsafe-inline';" in policy
    assert "connect-src 'self';" in policy
    assert 'https:' not in policy


@pytest.mark.asyncio
async def test_generated_audio_permission_does_not_expand_other_routes():
    middleware = SecurityHeadersMiddleware(app=lambda scope, receive, send: None)

    async def call_next(request):
        return SimpleNamespace(headers={})

    response = await middleware.dispatch(SimpleNamespace(url=SimpleNamespace(path='/dispatch')), call_next)
    assert 'blob:' not in response.headers['Content-Security-Policy']
