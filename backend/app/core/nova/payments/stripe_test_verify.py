"""Read-only Stripe TEST verification for Payments Readiness.

Uses only GET retrieve/list operations. Never creates, updates, deletes,
registers, or sends events. Never persists Stripe responses.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from app.core.nova.payments.classify import classify_key_mode
from app.core.nova.payments.schemas import NovaPaymentsReadinessCheck
from app.modules.payments.stripe_payments import HANDLED_EVENT_TYPES
from app.modules.platform_ops.onboarding.connect_webhook import (
    CONNECT_V2_WEBHOOK_PATH,
    CONNECT_WEBHOOK_PATH,
    DESTINATION_V1,
    DESTINATION_V2,
    V1_REQUIRED_EVENT,
    V2_REQUIRED_EVENT,
    has_signed_test_delivery,
)

logger = logging.getLogger("amicor.nova.payments.test_verify")

APPROVED_PRODUCTION_ORIGIN = "https://amicor-health-isf-py.onrender.com"
CUSTOMER_PAYMENT_WEBHOOK_PATH = "/api/payments/stripe/webhook"
CUSTOMER_PAYMENT_WEBHOOK_URL = f"{APPROVED_PRODUCTION_ORIGIN}{CUSTOMER_PAYMENT_WEBHOOK_PATH}"
CONNECT_WEBHOOK_URL = f"{APPROVED_PRODUCTION_ORIGIN}{CONNECT_WEBHOOK_PATH}"
CONNECT_V2_WEBHOOK_URL = f"{APPROVED_PRODUCTION_ORIGIN}{CONNECT_V2_WEBHOOK_PATH}"
CUSTOMER_REQUIRED_EVENTS = frozenset(HANDLED_EVENT_TYPES)
CONNECT_V1_REQUIRED_EVENTS = frozenset({V1_REQUIRED_EVENT})
CONNECT_V2_REQUIRED_EVENTS = frozenset({V2_REQUIRED_EVENT})
CONNECT_REQUIRED_EVENTS = CONNECT_V1_REQUIRED_EVENTS
_ROUTES_FILE = Path(__file__).resolve().parents[3] / "modules" / "platform_ops" / "routes.py"

CACHE_TTL_SECONDS = 300
VERIFY_TIMEOUT_SECONDS = 8
RATE_LIMIT = 4
RATE_WINDOW_SECONDS = 300

_CACHE: dict[tuple[str, str], tuple[float, "SafeVerifySnapshot"]] = {}
_RATE: dict[str, list[float]] = {}
_ADAPTER_OVERRIDE: "StripeTestReader | None" = None


class StripeTestReader(Protocol):
    def retrieve_platform_balance(self) -> dict[str, Any]:
        ...

    def list_webhook_summaries(self) -> list[dict[str, Any]]:
        ...

    def list_event_destination_summaries(self) -> list[dict[str, Any]]:
        ...


class RateLimited(RuntimeError):
    pass


@dataclass(frozen=True)
class SafeVerifySnapshot:
    organization_id: str
    environment: str
    checked_at: str
    auth_verified: bool
    checks: tuple[NovaPaymentsReadinessCheck, ...]


def set_test_reader_override(reader: StripeTestReader | None) -> None:
    global _ADAPTER_OVERRIDE
    _ADAPTER_OVERRIDE = reader


def reset_test_verification_state() -> None:
    _CACHE.clear()
    _RATE.clear()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(
    *,
    key: str,
    label: str,
    status: str,
    explanation: str,
    evidence_source: str,
    classification: str | None = None,
) -> NovaPaymentsReadinessCheck:
    return NovaPaymentsReadinessCheck(
        key=key,
        label=label,
        status=status,  # type: ignore[arg-type]
        classification=classification,
        explanation=explanation,
        evidence_source=evidence_source,
    )


def _classify_secret() -> tuple[str, bool, str | None]:
    raw = os.getenv("STRIPE_SECRET_KEY")
    classified = classify_key_mode(raw)
    raw = None
    return classified.status, classified.present, classified.mode


def _secret_present(name: str) -> bool:
    raw = os.getenv(name)
    present = bool(raw and str(raw).strip())
    raw = None
    return present


def _route_exists(needle: str) -> bool:
    try:
        return needle in _ROUTES_FILE.read_text(encoding="utf-8")
    except Exception:
        return False


def webhook_urls_exactly_equal(candidate: str, expected: str) -> bool:
    raw = str(candidate or "").strip()
    if not raw or raw.startswith("//") or "\\" in raw:
        return False
    parsed = urlparse(raw)
    want = urlparse(expected)
    if parsed.scheme != "https" or want.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False
    hostname = (parsed.hostname or "").lower()
    expected_host = (want.hostname or "").lower()
    if hostname != expected_host:
        return False
    if parsed.port not in {None, 443}:
        return False
    if parsed.netloc.lower() not in {expected_host, f"{expected_host}:443"}:
        return False
    if parsed.path != want.path:
        return False
    if parsed.query or parsed.fragment:
        return False
    return True


def _event_coverage(enabled: object, required: frozenset[str]) -> str:
    if not isinstance(enabled, list):
        return "not verified"
    have = {str(item) for item in enabled if isinstance(item, str)}
    wildcard = "*" in have
    missing_v1 = []
    unconfirmed_v2 = []
    for event_type in required:
        if event_type in have:
            continue
        if event_type.startswith("v2."):
            unconfirmed_v2.append(event_type)
            continue
        if wildcard:
            continue
        missing_v1.append(event_type)
    if missing_v1:
        return "no"
    if unconfirmed_v2:
        return "not verified"
    return "yes"


def _scope_value(row: dict[str, Any], *, source: str) -> str:
    if source == "webhook_endpoint":
        if "connect" not in row:
            return "not verified"
        return "yes" if row.get("connect") is True else "no"
    events_from = row.get("events_from")
    if events_from is None:
        return "not verified"
    if not isinstance(events_from, list):
        return "not verified"
    tokens = {str(item) for item in events_from if isinstance(item, str)}
    if "@accounts" in tokens or "@organization_members/@accounts" in tokens:
        return "yes"
    return "no"


def _enabled_value(status: object) -> str:
    enabled_value = str(status or "").strip().lower()
    if enabled_value == "enabled":
        return "yes"
    if enabled_value == "disabled":
        return "no"
    return "not verified"


def _take_rate_slot(user_id: str, organization_id: str) -> None:
    now = time.monotonic()
    cutoff = now - RATE_WINDOW_SECONDS
    for key in (f"user:{user_id}", f"org:{organization_id}"):
        bucket = [stamp for stamp in _RATE.get(key, []) if stamp >= cutoff]
        if len(bucket) >= RATE_LIMIT:
            _RATE[key] = bucket
            raise RateLimited()
        bucket.append(now)
        _RATE[key] = bucket


def _cache_get(organization_id: str, environment: str) -> SafeVerifySnapshot | None:
    key = (organization_id, environment)
    packed = _CACHE.get(key)
    if packed is None:
        return None
    stored_at, snapshot = packed
    if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return snapshot


def _cache_put(snapshot: SafeVerifySnapshot) -> None:
    _CACHE[(snapshot.organization_id, snapshot.environment)] = (time.monotonic(), snapshot)


class LiveStripeTestReader:
    """Pinned Stripe SDK GET-only adapter. Never mutates Stripe objects."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def _client(self):
        import stripe

        return stripe.StripeClient(self._api_key, max_network_retries=0)

    def retrieve_platform_balance(self) -> dict[str, Any]:
        retrieved = self._client().v1.balance.retrieve()
        payload = retrieved.to_dict() if hasattr(retrieved, "to_dict") else dict(retrieved)
        return {
            "object": payload.get("object"),
            "livemode": payload.get("livemode"),
        }

    def list_webhook_summaries(self) -> list[dict[str, Any]]:
        listed = self._client().v1.webhook_endpoints.list({"limit": 100})
        payload = listed.to_dict() if hasattr(listed, "to_dict") else dict(listed)
        rows = payload.get("data") if isinstance(payload, dict) else None
        summaries: list[dict[str, Any]] = []
        if not isinstance(rows, list):
            return summaries
        for item in rows:
            if not isinstance(item, dict):
                if hasattr(item, "to_dict"):
                    item = item.to_dict()
                else:
                    continue
            summary = {
                "url": item.get("url"),
                "status": item.get("status"),
                "enabled_events": item.get("enabled_events"),
                "livemode": item.get("livemode"),
            }
            if "connect" in item:
                summary["connect"] = item.get("connect")
            summaries.append(summary)
        return summaries

    def list_event_destination_summaries(self) -> list[dict[str, Any]]:
        listed = self._client().v2.core.event_destinations.list(
            {"limit": 100, "include": ["webhook_endpoint.url"]}
        )
        payload = listed.to_dict() if hasattr(listed, "to_dict") else dict(listed)
        rows = payload.get("data") if isinstance(payload, dict) else None
        summaries: list[dict[str, Any]] = []
        if not isinstance(rows, list):
            return summaries
        for item in rows:
            if not isinstance(item, dict):
                if hasattr(item, "to_dict"):
                    item = item.to_dict()
                else:
                    continue
            endpoint = item.get("webhook_endpoint")
            url = None
            if isinstance(endpoint, dict):
                url = endpoint.get("url")
            summaries.append(
                {
                    "url": url,
                    "status": item.get("status"),
                    "enabled_events": item.get("enabled_events"),
                    "livemode": item.get("livemode"),
                    "event_payload": item.get("event_payload"),
                    "events_from": item.get("events_from"),
                    "type": item.get("type"),
                }
            )
        return summaries


def _reader() -> StripeTestReader:
    if _ADAPTER_OVERRIDE is not None:
        return _ADAPTER_OVERRIDE
    raw = os.getenv("STRIPE_SECRET_KEY")
    key = str(raw or "").strip()
    raw = None
    return LiveStripeTestReader(key)


def _call_with_timeout(func, *args):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func, *args)
        return future.result(timeout=VERIFY_TIMEOUT_SECONDS)


def _inspect_webhooks(
    summaries: list[dict[str, Any]],
    *,
    expected_url: str,
    required_events: frozenset[str],
) -> tuple[str, str, str, str]:
    match = None
    for row in summaries:
        if webhook_urls_exactly_equal(str(row.get("url") or ""), expected_url):
            match = row
            break
    if match is None:
        return "no", "not verified", "not verified", "no"
    enabled = _enabled_value(match.get("status"))
    coverage = _event_coverage(match.get("enabled_events"), required_events)
    testdata = match.get("livemode") is False
    test_verified = "yes" if testdata and enabled == "yes" else "no"
    return "yes", enabled, coverage, test_verified


def _inspect_destination(
    webhook_summaries: list[dict[str, Any]],
    destination_summaries: list[dict[str, Any]],
    *,
    expected_url: str,
    required_events: frozenset[str],
    expected_payload: str,
    listed: bool,
) -> tuple[str, str, str, str, str]:
    match: dict[str, Any] | None = None
    source = ""
    if expected_payload == "snapshot":
        for row in webhook_summaries:
            if webhook_urls_exactly_equal(str(row.get("url") or ""), expected_url):
                match = row
                source = "webhook_endpoint"
                break
    if match is None:
        for row in destination_summaries:
            if str(row.get("type") or "") not in {"", "webhook_endpoint"}:
                continue
            if row.get("event_payload") != expected_payload:
                continue
            if webhook_urls_exactly_equal(str(row.get("url") or ""), expected_url):
                match = row
                source = "event_destination"
                break
    if match is None:
        return "no", "not verified", "not verified", "no", "not verified" if listed else "not verified"
    enabled = _enabled_value(match.get("status"))
    coverage = _event_coverage(match.get("enabled_events"), required_events)
    testdata = match.get("livemode") is False
    test_verified = "yes" if testdata and enabled == "yes" else "no"
    scope = _scope_value(match, source=source)
    return "yes", enabled, coverage, test_verified, scope


def _registration_status(exact: str, enabled: str, test_verified: str, listed: bool) -> str:
    if not listed:
        return "Not verified"
    if exact == "yes" and enabled == "yes" and test_verified == "yes":
        return "Verified"
    if exact == "no":
        return "Missing"
    return "Not verified"


def _scope_status(scope: str, listed: bool, exact: str) -> str:
    if not listed:
        return "Not verified"
    if exact != "yes":
        return "Missing" if exact == "no" else "Not verified"
    if scope == "yes":
        return "Verified"
    if scope == "no":
        return "Missing"
    return "Not verified"


def _coverage_status(listed: bool, exact: str, coverage: str) -> str:
    if not listed or exact != "yes":
        return "Not verified"
    if coverage == "yes":
        return "Verified"
    return "Not verified"


def _signing_check(*, env_name: str, label: str, key: str) -> NovaPaymentsReadinessCheck:
    present = _secret_present(env_name)
    return _check(
        key=key,
        label=label,
        status="Configured" if present else "Missing",
        explanation=(
            "A signing secret is present. Presence is not signed TEST delivery."
            if present
            else "No signing secret is configured. Presence is not signed TEST delivery."
        ),
        evidence_source=f"{env_name} presence boolean",
    )


def _route_check(*, key: str, label: str, needle: str, route_path: str) -> NovaPaymentsReadinessCheck:
    exists = _route_exists(needle)
    return _check(
        key=key,
        label=label,
        status="Configured" if exists else "Missing",
        explanation=(
            f"POST {route_path} exists in repository code. Route existence is not Stripe registration."
            if exists
            else f"POST {route_path} was not found. Route existence is separate from configuration."
        ),
        evidence_source="backend/app/modules/platform_ops/routes.py",
    )


def _signed_delivery_check(*, key: str, label: str, destination: str, event_type: str) -> NovaPaymentsReadinessCheck:
    verified = has_signed_test_delivery(destination=destination, event_type=event_type)
    return _check(
        key=key,
        label=label,
        status="Verified" if verified else "Not verified",
        explanation=(
            "The deployed route accepted an authentic Stripe-signed TEST event for this destination."
            if verified
            else (
                "Signed TEST delivery is Verified only after this deployed route accepts an authentic "
                "Stripe-signed TEST event. Secret presence, route existence, listing, and event "
                "selection are not signed delivery."
            )
        ),
        evidence_source="Connect destination TEST delivery ledger presence boolean",
    )


def _empty_destination() -> tuple[str, str, str, str, str]:
    return "no", "not verified", "not verified", "no", "not verified"


def _build_verification_checks(
    *,
    checked_at: str,
    auth_status: str,
    auth_explain: str,
    mode: str | None,
    auth_evidence: str,
    listed: bool,
    dest_listed: bool,
    customer_exact: str,
    customer_enabled: str,
    customer_coverage: str,
    customer_test: str,
    v1_exact: str,
    v1_enabled: str,
    v1_coverage: str,
    v1_test: str,
    v1_scope: str,
    v2_exact: str,
    v2_enabled: str,
    v2_coverage: str,
    v2_test: str,
    v2_scope: str,
) -> list[NovaPaymentsReadinessCheck]:
    v1_listed = listed or dest_listed
    return [
        _check(
            key="test_platform_auth",
            label="TEST platform authentication",
            status=auth_status,
            classification=mode,
            explanation=f"{auth_explain} Last safe verification attempt: {checked_at}.",
            evidence_source=auth_evidence,
        ),
        _check(
            key="customer_webhook_registration",
            label="Customer webhook exact registration",
            status=_registration_status(customer_exact, customer_enabled, customer_test, listed),
            explanation=(
                f"Expected URL: {CUSTOMER_PAYMENT_WEBHOOK_URL}. Exact match found: {customer_exact}. "
                f"Endpoint enabled: {customer_enabled}. Required-event coverage complete: {customer_coverage}. "
                f"TEST registration verified: {customer_test}. Checked at {checked_at}."
            ),
            evidence_source="GET /v1/webhook_endpoints" if listed else "GET /v1/webhook_endpoints (not called)",
        ),
        _check(
            key="customer_webhook_events",
            label="Customer webhook required-event coverage",
            status=_coverage_status(listed, customer_exact, customer_coverage),
            explanation=(
                "Required events are payment_intent.succeeded and payment_intent.payment_failed. "
                f"Coverage: {customer_coverage}."
            ),
            evidence_source="Implemented customer-payment handlers",
        ),
        _signing_check(
            env_name="STRIPE_PAYMENT_WEBHOOK_SECRET",
            label="Customer webhook signing-secret match",
            key="customer_webhook_signing_match",
        ),
        _route_check(
            key="connect_v1_webhook_route",
            label="Connect v1 snapshot route exists",
            needle='@router.post("/stripe/webhook")',
            route_path=CONNECT_WEBHOOK_PATH,
        ),
        _signing_check(
            env_name="STRIPE_WEBHOOK_SECRET",
            label="Connect v1 snapshot signing secret",
            key="connect_v1_webhook_secret",
        ),
        _check(
            key="connect_v1_webhook_registration",
            label="Connect v1 snapshot exact TEST registration",
            status=_registration_status(v1_exact, v1_enabled, v1_test, v1_listed),
            explanation=(
                f"Expected URL: {CONNECT_WEBHOOK_URL}. Exact match found: {v1_exact}. "
                f"Endpoint enabled: {v1_enabled}. Required-event coverage complete: {v1_coverage}. "
                f"TEST registration verified: {v1_test}. Checked at {checked_at}."
            ),
            evidence_source="GET /v1/webhook_endpoints and GET /v2/core/event_destinations",
        ),
        _check(
            key="connect_v1_webhook_scope",
            label="Connect v1 snapshot event scope",
            status=_scope_status(v1_scope, v1_listed, v1_exact),
            explanation=(
                "Required scope is connected accounts (classic connect=true or events_from @accounts). "
                f"Scope: {v1_scope}."
            ),
            evidence_source="Connect webhook connect flag or event-destination events_from",
        ),
        _check(
            key="connect_v1_webhook_events",
            label="Connect v1 snapshot required-event coverage",
            status=_coverage_status(v1_listed, v1_exact, v1_coverage),
            explanation=f"Required event is {V1_REQUIRED_EVENT}. Coverage: {v1_coverage}.",
            evidence_source="Connect v1 snapshot destination contract",
        ),
        _signed_delivery_check(
            key="connect_v1_signed_delivery",
            label="Connect v1 snapshot signed TEST delivery",
            destination=DESTINATION_V1,
            event_type=V1_REQUIRED_EVENT,
        ),
        _route_check(
            key="connect_v2_webhook_route",
            label="Connect v2 thin route exists",
            needle='@router.post("/stripe/v2/webhook")',
            route_path=CONNECT_V2_WEBHOOK_PATH,
        ),
        _signing_check(
            env_name="STRIPE_CONNECT_V2_WEBHOOK_SECRET",
            label="Connect v2 thin signing secret",
            key="connect_v2_webhook_secret",
        ),
        _check(
            key="connect_v2_webhook_registration",
            label="Connect v2 thin exact TEST registration",
            status=_registration_status(v2_exact, v2_enabled, v2_test, dest_listed),
            explanation=(
                f"Expected URL: {CONNECT_V2_WEBHOOK_URL}. Exact match found: {v2_exact}. "
                f"Endpoint enabled: {v2_enabled}. Required-event coverage complete: {v2_coverage}. "
                f"TEST registration verified: {v2_test}. Checked at {checked_at}."
            ),
            evidence_source="GET /v2/core/event_destinations",
        ),
        _check(
            key="connect_v2_webhook_scope",
            label="Connect v2 thin event scope",
            status=_scope_status(v2_scope, dest_listed, v2_exact),
            explanation=(
                "Required scope is events_from @accounts for managed Connect accounts. "
                f"Scope: {v2_scope}."
            ),
            evidence_source="Event-destination events_from",
        ),
        _check(
            key="connect_v2_webhook_events",
            label="Connect v2 thin required-event coverage",
            status=_coverage_status(dest_listed, v2_exact, v2_coverage),
            explanation=f"Required event is {V2_REQUIRED_EVENT}. Coverage: {v2_coverage}.",
            evidence_source="Connect v2 thin destination contract",
        ),
        _signed_delivery_check(
            key="connect_v2_signed_delivery",
            label="Connect v2 thin signed TEST delivery",
            destination=DESTINATION_V2,
            event_type=V2_REQUIRED_EVENT,
        ),
        _check(
            key="connect_webhook_registration",
            label="Connect webhook exact registration",
            status=_registration_status(v1_exact, v1_enabled, v1_test, v1_listed),
            explanation=(
                f"Expected URL: {CONNECT_WEBHOOK_URL}. Exact match found: {v1_exact}. "
                f"Endpoint enabled: {v1_enabled}. Required-event coverage complete: {v1_coverage}. "
                f"TEST registration verified: {v1_test}. Checked at {checked_at}."
            ),
            evidence_source="GET /v1/webhook_endpoints and GET /v2/core/event_destinations",
        ),
        _check(
            key="connect_webhook_events",
            label="Connect webhook required-event coverage",
            status=_coverage_status(v1_listed, v1_exact, v1_coverage),
            explanation=f"Required event is {V1_REQUIRED_EVENT}. Coverage: {v1_coverage}.",
            evidence_source="Connect v1 snapshot destination contract",
        ),
        _signing_check(
            env_name="STRIPE_WEBHOOK_SECRET",
            label="Connect webhook signing-secret match",
            key="connect_webhook_signing_match",
        ),
        _check(
            key="test_verification_checked_at",
            label="Last safe verification attempt in UTC",
            status="Not applicable",
            explanation=f"Last safe verification attempt: {checked_at}.",
            evidence_source="In-memory verification cache",
        ),
    ]


def _classified_only_checks(*, checked_at: str) -> list[NovaPaymentsReadinessCheck]:
    status, present, mode = _classify_secret()
    if status == "Missing" or not present:
        auth_status, auth_explain = "Missing", "No TEST credential is configured. Stripe was not contacted."
        auth_evidence = "GET /v1/balance (not called)"
    elif mode == "LIVE":
        auth_status, auth_explain = "Blocked", "A LIVE credential is classified. LIVE verification is unauthorized. Stripe was not contacted."
        auth_evidence = "GET /v1/balance (not called)"
    elif mode != "TEST":
        auth_status, auth_explain = "Not verified", "The credential could not be classified as TEST. Stripe was not contacted."
        auth_evidence = "GET /v1/balance (not called)"
    else:
        auth_status, auth_explain = "Not verified", "TEST verification has not been requested in this response."
        auth_evidence = "GET /v1/balance (not called)"
    empty = _empty_destination()
    return _build_verification_checks(
        checked_at=checked_at,
        auth_status=auth_status,
        auth_explain=auth_explain,
        mode=mode,
        auth_evidence=auth_evidence,
        listed=False,
        dest_listed=False,
        customer_exact="no",
        customer_enabled="not verified",
        customer_coverage="not verified",
        customer_test="no",
        v1_exact=empty[0],
        v1_enabled=empty[1],
        v1_coverage=empty[2],
        v1_test=empty[3],
        v1_scope=empty[4],
        v2_exact=empty[0],
        v2_enabled=empty[1],
        v2_coverage=empty[2],
        v2_test=empty[3],
        v2_scope=empty[4],
    )


def classified_verification_section() -> list[NovaPaymentsReadinessCheck]:
    return _classified_only_checks(checked_at="not checked")


def cached_verification_section(organization_id: str) -> list[NovaPaymentsReadinessCheck]:
    _status, _present, mode = _classify_secret()
    environment = mode or "unknown"
    snapshot = _cache_get(organization_id, environment)
    if snapshot is not None:
        return list(snapshot.checks)
    return classified_verification_section()


def _safe_auth_result(balance: dict[str, Any]) -> str:
    if not isinstance(balance, dict):
        return "Not verified"
    if balance.get("livemode") is True:
        return "Blocked"
    if balance.get("object") == "balance" and balance.get("livemode") is False:
        return "Verified"
    return "Not verified"


def run_test_verification(*, organization_id: str, user_id: str) -> list[NovaPaymentsReadinessCheck]:
    _take_rate_slot(user_id, organization_id)
    status, present, mode = _classify_secret()
    environment = mode or "unknown"
    checked_at = _utc_now()
    cached = _cache_get(organization_id, environment)

    if status == "Missing" or not present or mode != "TEST":
        checks = _classified_only_checks(checked_at=checked_at)
        snapshot = SafeVerifySnapshot(
            organization_id=organization_id,
            environment=environment,
            checked_at=checked_at,
            auth_verified=False,
            checks=tuple(checks),
        )
        if cached is None or not cached.auth_verified:
            _cache_put(snapshot)
        return list((cached.checks if cached and cached.auth_verified else snapshot.checks))

    reader = _reader()
    try:
        balance = _call_with_timeout(reader.retrieve_platform_balance)
        auth_status = _safe_auth_result(balance)
    except Exception:
        logger.info("test_verify_auth_unavailable")
        if cached is not None and cached.auth_verified:
            return list(cached.checks)
        checks = _classified_only_checks(checked_at=checked_at)
        checks[0] = _check(
            key="test_platform_auth",
            label="TEST platform authentication",
            status="Not verified",
            classification="TEST",
            explanation=f"TEST retrieval could not be completed. Last safe verification attempt: {checked_at}.",
            evidence_source="GET /v1/balance",
        )
        _cache_put(
            SafeVerifySnapshot(
                organization_id=organization_id,
                environment=environment,
                checked_at=checked_at,
                auth_verified=False,
                checks=tuple(checks),
            )
        )
        return checks

    listed = False
    dest_listed = False
    summaries: list[dict[str, Any]] = []
    destinations: list[dict[str, Any]] = []
    try:
        summaries = _call_with_timeout(reader.list_webhook_summaries)
        listed = True
    except Exception:
        logger.info("test_verify_webhooks_unavailable")
        summaries = []
    try:
        destinations = _call_with_timeout(reader.list_event_destination_summaries)
        dest_listed = True
    except Exception:
        logger.info("test_verify_event_destinations_unavailable")
        destinations = []

    customer = _inspect_webhooks(
        summaries,
        expected_url=CUSTOMER_PAYMENT_WEBHOOK_URL,
        required_events=CUSTOMER_REQUIRED_EVENTS,
    )
    v1 = _inspect_destination(
        summaries,
        destinations,
        expected_url=CONNECT_WEBHOOK_URL,
        required_events=CONNECT_V1_REQUIRED_EVENTS,
        expected_payload="snapshot",
        listed=listed or dest_listed,
    )
    v2 = _inspect_destination(
        summaries,
        destinations,
        expected_url=CONNECT_V2_WEBHOOK_URL,
        required_events=CONNECT_V2_REQUIRED_EVENTS,
        expected_payload="thin",
        listed=dest_listed,
    )
    customer_exact, customer_enabled, customer_coverage, customer_test = customer

    auth_explain = {
        "Verified": "Authenticated TEST retrieval succeeded for the configured platform credential.",
        "Blocked": "The retrieved Stripe data was LIVE. LIVE verification is unauthorized.",
        "Not verified": "TEST retrieval did not return a usable TEST platform balance.",
    }[auth_status]

    checks = _build_verification_checks(
        checked_at=checked_at,
        auth_status=auth_status,
        auth_explain=auth_explain,
        mode="TEST",
        auth_evidence="GET /v1/balance",
        listed=listed,
        dest_listed=dest_listed,
        customer_exact=customer_exact,
        customer_enabled=customer_enabled,
        customer_coverage=customer_coverage,
        customer_test=customer_test,
        v1_exact=v1[0],
        v1_enabled=v1[1],
        v1_coverage=v1[2],
        v1_test=v1[3],
        v1_scope=v1[4],
        v2_exact=v2[0],
        v2_enabled=v2[1],
        v2_coverage=v2[2],
        v2_test=v2[3],
        v2_scope=v2[4],
    )
    snapshot = SafeVerifySnapshot(
        organization_id=organization_id,
        environment=environment,
        checked_at=checked_at,
        auth_verified=auth_status == "Verified",
        checks=tuple(checks),
    )
    if snapshot.auth_verified or cached is None or not cached.auth_verified:
        _cache_put(snapshot)
        return checks
    return list(cached.checks)
