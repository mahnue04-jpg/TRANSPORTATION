"""Google OAuth token exchange. Live HTTP is hard-off unless a client is injected."""

from __future__ import annotations

import os
from typing import Any, Protocol
from urllib.parse import urlencode

from app.core.nova.growth_agent.flags import REAL_CALENDAR_WRITE, google_oauth_configured


class OAuthHttpError(Exception):
    """Safe error — code only, never token material in the message."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _HttpClient(Protocol):
    def post(self, url: str, *, data: dict[str, str], timeout: float = ...) -> Any: ...


_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _live_allowed(*, http_client: object | None) -> bool:
    if http_client is not None:
        return True
    if not REAL_CALENDAR_WRITE:
        return False
    if not google_oauth_configured():
        return False
    return True


def _client_credentials() -> tuple[str, str]:
    client_id = str(os.getenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = str(os.getenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise OAuthHttpError("OAUTH_LIVE_DISABLED")
    return client_id, client_secret


def _response_json(response: Any) -> dict[str, Any]:
    if hasattr(response, "json"):
        payload = response.json()
    elif hasattr(response, "raise_for_status"):
        response.raise_for_status()
        payload = response.json()
    else:
        raise OAuthHttpError("OAUTH_EXCHANGE_FAILED")
    if not isinstance(payload, dict):
        raise OAuthHttpError("OAUTH_EXCHANGE_FAILED")
    if "error" in payload:
        code = str(payload.get("error") or "OAUTH_EXCHANGE_FAILED").upper().replace(" ", "_")
        raise OAuthHttpError(code[:80] or "OAUTH_EXCHANGE_FAILED")
    return payload


def exchange_authorization_code(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    http_client: _HttpClient | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens. Inject http_client in tests."""
    if not code or not code_verifier or not redirect_uri:
        raise OAuthHttpError("INVALID_OAUTH_REQUEST")
    if not _live_allowed(http_client=http_client):
        raise OAuthHttpError("OAUTH_LIVE_DISABLED")

    client_id, client_secret = _client_credentials()
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": code_verifier,
    }

    if http_client is not None:
        response = http_client.post(_TOKEN_URL, data=body, timeout=15.0)
        return _response_json(response)

    import httpx

    with httpx.Client(timeout=15.0) as client:
        response = client.post(_TOKEN_URL, data=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise OAuthHttpError("OAUTH_EXCHANGE_FAILED")
        if "error" in payload:
            raise OAuthHttpError("OAUTH_EXCHANGE_FAILED")
        return payload


def refresh_access_token(
    *,
    refresh_token: str,
    http_client: _HttpClient | None = None,
) -> dict[str, Any]:
    """Refresh a Google access token. Inject http_client in tests."""
    if not refresh_token:
        raise OAuthHttpError("INVALID_OAUTH_REQUEST")
    if not _live_allowed(http_client=http_client):
        raise OAuthHttpError("OAUTH_LIVE_DISABLED")

    client_id, client_secret = _client_credentials()
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    if http_client is not None:
        response = http_client.post(_TOKEN_URL, data=body, timeout=15.0)
        return _response_json(response)

    import httpx

    with httpx.Client(timeout=15.0) as client:
        response = client.post(_TOKEN_URL, data=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise OAuthHttpError("OAUTH_EXCHANGE_FAILED")
        if "error" in payload:
            raise OAuthHttpError("OAUTH_EXCHANGE_FAILED")
        return payload


def build_google_authorize_query(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: tuple[str, ...],
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return urlencode(params)