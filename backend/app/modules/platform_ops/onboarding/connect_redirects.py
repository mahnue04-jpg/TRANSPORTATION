"""Server-side Stripe Connect return and refresh URL construction.

Production permits only the exact approved HTTPS origin. Browser-supplied
origins, Host headers, and request URLs are never used.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, unquote, urlparse

APPROVED_PRODUCTION_HOST = "amicor-health-isf-py.onrender.com"
APPROVED_PRODUCTION_ORIGIN = "https://amicor-health-isf-py.onrender.com"
RESUME_PATH = "/platform-ops/driver-apply"
WORK_SETUP_RETURN = "stripe_return"
WORK_SETUP_REFRESH = "stripe_refresh"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
_GENERIC_ERROR = "Payout setup could not be started."


class ConnectRedirectError(ValueError):
    def __init__(self) -> None:
        super().__init__(_GENERIC_ERROR)


def _explicit_environment() -> str:
    return (os.getenv("AMICOR_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "").strip().lower()


def is_explicit_local_or_test_environment() -> bool:
    explicit = _explicit_environment()
    if explicit in {"production", "prod"}:
        return False
    if explicit in {"test", "testing", "development", "dev", "local"}:
        return True
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def is_production_runtime() -> bool:
    if is_explicit_local_or_test_environment():
        return False
    explicit = _explicit_environment()
    if explicit in {"production", "prod"}:
        return True
    try:
        from app.runtime_contract import RUNTIME_ENVIRONMENT

        if str(RUNTIME_ENVIRONMENT or "").strip().lower() in {"production", "prod"}:
            return True
    except Exception:
        return False
    return False


def _canonical_origin() -> str:
    if is_explicit_local_or_test_environment():
        return "http://127.0.0.1"
    if not is_production_runtime():
        raise ConnectRedirectError()
    if APPROVED_PRODUCTION_ORIGIN != f"https://{APPROVED_PRODUCTION_HOST}":
        raise ConnectRedirectError()
    if not APPROVED_PRODUCTION_ORIGIN.startswith("https://"):
        raise ConnectRedirectError()
    return APPROVED_PRODUCTION_ORIGIN


def _fully_unquote(value: str, rounds: int = 5) -> str:
    current = value
    for _ in range(rounds):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def validate_connect_redirect_url(url: str, *, production: bool) -> str:
    raw = str(url or "").strip()
    if not raw:
        raise ConnectRedirectError()
    if raw.startswith("//") or raw.startswith("\\\\") or "\\" in raw:
        raise ConnectRedirectError()
    decoded = _fully_unquote(raw)
    if decoded.startswith("//") or decoded.startswith("\\\\"):
        raise ConnectRedirectError()

    parsed = urlparse(raw)
    decoded_parsed = urlparse(decoded)
    if parsed.scheme not in {"http", "https"}:
        raise ConnectRedirectError()
    if parsed.username or parsed.password or decoded_parsed.username or decoded_parsed.password:
        raise ConnectRedirectError()
    if parsed.fragment or decoded_parsed.fragment:
        raise ConnectRedirectError()

    hostname = (parsed.hostname or "").lower()
    decoded_host = (decoded_parsed.hostname or "").lower()
    if not hostname or not decoded_host:
        raise ConnectRedirectError()

    if production:
        if parsed.scheme != "https" or decoded_parsed.scheme != "https":
            raise ConnectRedirectError()
        if hostname != APPROVED_PRODUCTION_HOST or decoded_host != APPROVED_PRODUCTION_HOST:
            raise ConnectRedirectError()
        if parsed.port not in {None, 443} or decoded_parsed.port not in {None, 443}:
            raise ConnectRedirectError()
        if parsed.netloc.lower() != APPROVED_PRODUCTION_HOST:
            raise ConnectRedirectError()
    else:
        if hostname not in LOCAL_HOSTS or decoded_host not in LOCAL_HOSTS:
            raise ConnectRedirectError()

    if parsed.path != RESUME_PATH or decoded_parsed.path != RESUME_PATH:
        raise ConnectRedirectError()

    query = parse_qs(parsed.query, keep_blank_values=True)
    decoded_query = parse_qs(decoded_parsed.query, keep_blank_values=True)
    if set(query.keys()) != {"work_setup"} or set(decoded_query.keys()) != {"work_setup"}:
        raise ConnectRedirectError()
    values = query.get("work_setup") or []
    decoded_values = decoded_query.get("work_setup") or []
    allowed = {WORK_SETUP_RETURN, WORK_SETUP_REFRESH}
    if len(values) != 1 or values[0] not in allowed:
        raise ConnectRedirectError()
    if len(decoded_values) != 1 or decoded_values[0] not in allowed:
        raise ConnectRedirectError()

    lowered = decoded.lower()
    if "token=" in lowered or "applicant_token=" in lowered:
        raise ConnectRedirectError()
    return raw


def build_connect_redirect_urls() -> tuple[str, str]:
    origin = _canonical_origin()
    production = is_production_runtime()
    return_url = f"{origin}{RESUME_PATH}?work_setup={WORK_SETUP_RETURN}"
    refresh_url = f"{origin}{RESUME_PATH}?work_setup={WORK_SETUP_REFRESH}"
    validate_connect_redirect_url(return_url, production=production)
    validate_connect_redirect_url(refresh_url, production=production)
    return return_url, refresh_url
