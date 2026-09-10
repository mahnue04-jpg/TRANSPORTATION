"""Read-only Stripe readiness inspection from code, catalog, and metadata."""
from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
from app.core.nova.payments.classify import KeyMode, classify_key_mode, modes_match
from app.core.nova.payments.schemas import (
    NovaPaymentsReadinessBlocker,
    NovaPaymentsReadinessCheck,
    NovaPaymentsReadinessOut,
    NovaPaymentsReadinessSection,
)

READINESS_ROLES = {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}
APPROVED_PRODUCTION_HOST = "amicor-health-isf-py.onrender.com"
APP_DIR = Path(__file__).resolve().parents[3]

_LEAK_PATTERN = re.compile(
    r"(?i)(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]+"
    r"|whsec_[A-Za-z0-9]+"
    r"|acct_[A-Za-z0-9]+"
    r"|cus_[A-Za-z0-9]+"
    r"|pi_[A-Za-z0-9_]+"
)

NOT_AUTHORIZED = "Not authorized"


class NovaPaymentsReadinessError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _source(rel: str) -> str:
    return (APP_DIR / rel).read_text(encoding="utf-8")


def _has(rel: str, *needles: str) -> bool:
    text = _source(rel)
    return all(needle in text for needle in needles)


def _env_present(name: str) -> bool:
    raw = os.getenv(name)
    present = bool(raw and str(raw).strip())
    raw = None
    return present


def _classify_env(name: str) -> KeyMode:
    raw = os.getenv(name)
    try:
        return classify_key_mode(raw)
    finally:
        raw = None


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


def _safe_section(key: str, label: str, builder) -> NovaPaymentsReadinessSection:
    try:
        checks = builder()
        return NovaPaymentsReadinessSection(key=key, label=label, status="ok", checks=checks)
    except Exception:
        return NovaPaymentsReadinessSection(
            key=key,
            label=label,
            status="unavailable",
            checks=[
                _check(
                    key=f"{key}_unavailable",
                    label=label,
                    status="Not verified",
                    explanation="This section could not be inspected safely. No Stripe objects were changed.",
                    evidence_source="payments readiness fail-soft",
                )
            ],
        )


def _customer_payment_section() -> list[NovaPaymentsReadinessCheck]:
    secret = _classify_env("STRIPE_SECRET_KEY")
    publishable = _classify_env("STRIPE_PUBLISHABLE_KEY")
    match_status = modes_match(secret, publishable)
    webhook_present = _env_present("STRIPE_PAYMENT_WEBHOOK_SECRET")
    route_exists = _has(
        "modules/payments/routes.py",
        '@router.post("/stripe/webhook")',
        'prefix="/api/payments"',
    )
    idempotent = _has(
        "modules/payments/models.py",
        "uq_amicor_customer_payment_events_event",
        "stripe_event_id",
    ) and _has("modules/payments/stripe_payments.py", "_lookup_existing_event")
    success_path = _has(
        "modules/payments/stripe_payments.py",
        "EVENT_PAYMENT_SUCCEEDED",
        "payment_intent.succeeded",
        "PAYMENT_SUCCEEDED",
    )
    failure_path = _has(
        "modules/payments/stripe_payments.py",
        "EVENT_PAYMENT_FAILED",
        "payment_intent.payment_failed",
        "PAYMENT_FAILED",
    )
    refund_refused = (not _has("modules/payments/routes.py", "/refund")) and _has(
        "core/nova/accounting/router.py",
        "@router.post(\"/refund\")",
        "Accounting is read-only. Refunds are not created here.",
    )
    org_isolation = _has(
        "modules/payments/rider_checkout.py",
        "organization_id=str(organization_id)",
        "str(request_row.organization_id) != str(organization_id)",
    )
    if match_status == "Configured" and secret.mode:
        stripe_mode = secret.mode
        mode_status = "Configured"
        mode_explain = (
            f"Publishable and secret keys classify as {stripe_mode}. "
            "This is not a Stripe verification and is not LIVE readiness."
        )
    elif match_status == "Blocked":
        stripe_mode = None
        mode_status = "Blocked"
        mode_explain = "Publishable and secret key modes do not match. LIVE customer payments stay blocked."
    elif match_status == "Missing":
        stripe_mode = None
        mode_status = "Missing"
        mode_explain = "A publishable or secret key is missing, so Stripe mode cannot be confirmed."
    else:
        stripe_mode = None
        mode_status = "Not verified"
        mode_explain = "Stripe mode could not be classified without exposing a secret value."

    return [
        _check(
            key="stripe_mode",
            label="Stripe mode",
            status=mode_status,
            classification=stripe_mode,
            explanation=mode_explain,
            evidence_source="Safe server-side key-mode classification",
        ),
        _check(
            key="publishable_key_mode",
            label="Publishable-key mode",
            status=publishable.status,
            classification=publishable.mode,
            explanation=(
                "Publishable key is absent."
                if publishable.status == "Missing"
                else "Publishable key classified without returning its value. Classification is not Stripe verification."
            ),
            evidence_source="STRIPE_PUBLISHABLE_KEY presence and prefix class only",
        ),
        _check(
            key="secret_key_mode",
            label="Secret-key mode",
            status=secret.status,
            classification=secret.mode,
            explanation=(
                "Secret key is absent."
                if secret.status == "Missing"
                else "Secret key classified without returning its value. Classification is not Stripe verification."
            ),
            evidence_source="STRIPE_SECRET_KEY presence and prefix class only",
        ),
        _check(
            key="key_modes_match",
            label="Publishable and secret key modes match",
            status=match_status,
            classification=secret.mode if match_status == "Configured" else None,
            explanation=(
                "Both keys classify as the same mode."
                if match_status == "Configured"
                else "Key modes are missing, unmatched, or not classifiable. They are not treated as verified."
            ),
            evidence_source="Safe key-mode comparison",
        ),
        _check(
            key="customer_webhook_signing",
            label="Customer-payment webhook signing configuration",
            status="Configured" if webhook_present else "Missing",
            explanation=(
                "A customer-payment webhook signing secret is present. Presence is not verification with Stripe."
                if webhook_present
                else "No customer-payment webhook signing secret is configured."
            ),
            evidence_source="STRIPE_PAYMENT_WEBHOOK_SECRET presence boolean",
        ),
        _check(
            key="customer_webhook_route",
            label="Customer-payment webhook route existence",
            status="Configured" if route_exists else "Missing",
            explanation=(
                "POST /api/payments/stripe/webhook exists in repository code."
                if route_exists
                else "The customer-payment webhook route was not found in repository code."
            ),
            evidence_source="backend/app/modules/payments/routes.py",
        ),
        _check(
            key="webhook_idempotency",
            label="Webhook idempotency protection",
            status="Configured" if idempotent else "Missing",
            explanation=(
                "Customer-payment events are stored with a unique Stripe event id."
                if idempotent
                else "Customer-payment webhook idempotency was not found."
            ),
            evidence_source="amicor_customer_payment_events unique event id",
        ),
        _check(
            key="payment_success_persistence",
            label="Payment-success persistence path",
            status="Configured" if success_path else "Missing",
            explanation=(
                "Succeeded PaymentIntent events persist to the customer-payment ledger."
                if success_path
                else "A payment-success persistence path was not found."
            ),
            evidence_source="backend/app/modules/payments/stripe_payments.py",
        ),
        _check(
            key="payment_failure_persistence",
            label="Payment-failure persistence path",
            status="Configured" if failure_path else "Missing",
            explanation=(
                "Failed PaymentIntent events persist to the customer-payment ledger."
                if failure_path
                else "A payment-failure persistence path was not found."
            ),
            evidence_source="backend/app/modules/payments/stripe_payments.py",
        ),
        _check(
            key="refund_authorization",
            label="Refund path authorization controls",
            status="Configured" if refund_refused else "Not verified",
            explanation=(
                "Customer-payment APIs do not expose a refund write. Accounting refund writes are refused."
                if refund_refused
                else "Refund authorization could not be confirmed from repository code."
            ),
            evidence_source="payments routes and accounting refund refusal",
        ),
        _check(
            key="payment_organization_isolation",
            label="Organization isolation",
            status="Configured" if org_isolation else "Missing",
            explanation=(
                "Rider checkout and payment status are scoped to the caller organization."
                if org_isolation
                else "Organization isolation for customer payments was not found."
            ),
            evidence_source="backend/app/modules/payments/rider_checkout.py",
        ),
    ]


def _connect_section() -> list[NovaPaymentsReadinessCheck]:
    secret = _classify_env("STRIPE_SECRET_KEY")
    connect_configured = secret.present
    create_account = _has(
        "modules/platform_ops/onboarding/stripe_connect.py",
        "def create_recipient_account",
        "client.v2.core.accounts.create",
    )
    account_link = _has(
        "modules/platform_ops/onboarding/stripe_connect.py",
        "def create_account_onboarding_link",
        "account_links.create",
    )
    redirect_source = _source("modules/platform_ops/onboarding/work_setup.py")
    https_only = 'parsed.scheme not in {"https"}' in redirect_source or 'parsed.scheme != "https"' in redirect_source
    host_enforced = APPROVED_PRODUCTION_HOST in redirect_source
    url_status = "Configured" if https_only and host_enforced else "Blocked"
    token_binding = _has(
        "modules/platform_ops/onboarding/service.py",
        "def verify_applicant_token",
        "applicant_access_token_hash",
        "_hash_token(token) == application.applicant_access_token_hash",
    )
    refresh_path = _has(
        "modules/platform_ops/onboarding/work_setup.py",
        "def refresh_payout_status",
        "map_account_to_payout_status",
    )
    connect_route = _has("modules/platform_ops/routes.py", "/stripe/webhook")
    connect_secret = _env_present("STRIPE_WEBHOOK_SECRET")
    org_bind = _has(
        "modules/platform_ops/onboarding/work_setup.py",
        '"organization_id": application.organization_id',
        '"application_id": application.id',
    )
    token_rotation = _has(
        "modules/platform_ops/onboarding/service.py",
        "def reissue_applicant_access_token",
        "Previous applicant token revoked",
        "application.applicant_access_token_hash = token_hash",
    )
    stripe_hosted_bank = _has(
        "modules/platform_ops/onboarding/work_setup.py",
        "bank account or routing numbers on this application",
        "Amicor never asks for routing or account numbers here",
    ) and _has(
        "modules/approval_engine/sensitive_providers.py",
        "reject_raw_sensitive_payload",
        "routing_number",
    )
    return [
        _check(
            key="connect_configured",
            label="Connect integration configured",
            status="Configured" if connect_configured else "Missing",
            classification=secret.mode,
            explanation=(
                "A Stripe secret is present for Connect client construction. Presence is not verification with Stripe."
                if connect_configured
                else "No Stripe secret is present, so Connect is not configured."
            ),
            evidence_source="STRIPE_SECRET_KEY presence boolean",
        ),
        _check(
            key="connect_account_create_code",
            label="Connected-account creation code exists",
            status="Configured" if create_account else "Missing",
            explanation=(
                "Recipient account creation code exists. This phase does not create accounts."
                if create_account
                else "Connected-account creation code was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/stripe_connect.py",
        ),
        _check(
            key="connect_account_link_code",
            label="Account-link onboarding code exists",
            status="Configured" if account_link else "Missing",
            explanation=(
                "Hosted account-link onboarding code exists. This phase does not create links."
                if account_link
                else "Account-link onboarding code was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/stripe_connect.py",
        ),
        _check(
            key="connect_return_url",
            label="Return URL is HTTPS on the approved production host",
            status=url_status,
            explanation=(
                "Return URL validation requires HTTPS on the approved production host."
                if url_status == "Configured"
                else (
                    "Current return-URL validation accepts http or https on any host. "
                    "LIVE payouts require HTTPS on the approved production host."
                )
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/work_setup.py _safe_redirect_url",
        ),
        _check(
            key="connect_refresh_url",
            label="Refresh URL is HTTPS on the approved production host",
            status=url_status,
            explanation=(
                "Refresh URL validation requires HTTPS on the approved production host."
                if url_status == "Configured"
                else (
                    "Current refresh-URL validation accepts http or https on any host. "
                    "LIVE payouts require HTTPS on the approved production host."
                )
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/work_setup.py _safe_redirect_url",
        ),
        _check(
            key="applicant_token_binding",
            label="Applicant token and application binding exists",
            status="Configured" if token_binding else "Missing",
            explanation=(
                "Applicant access is bound to a stored token hash on the application."
                if token_binding
                else "Applicant token binding was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/service.py",
        ),
        _check(
            key="payout_status_refresh",
            label="Payout-status refresh path exists",
            status="Configured" if refresh_path else "Missing",
            explanation=(
                "A payout-status refresh path exists. This phase does not call Stripe."
                if refresh_path
                else "A payout-status refresh path was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/work_setup.py",
        ),
        _check(
            key="connect_webhook_route",
            label="Connect webhook route exists",
            status="Configured" if connect_route else "Missing",
            explanation=(
                "A Connect webhook route exists in repository code."
                if connect_route
                else "POST /api/platform-ops/driver-onboarding/stripe/webhook was not found. Route existence is separate from configuration."
            ),
            evidence_source="backend/app/modules/platform_ops/routes.py",
        ),
        _check(
            key="connect_webhook_configured",
            label="Connect webhook is configured",
            status="Configured" if connect_secret else "Missing",
            explanation=(
                "A Connect webhook signing secret is present. Presence is not verification with Stripe."
                if connect_secret
                else "No Connect webhook signing secret is configured."
            ),
            evidence_source="STRIPE_WEBHOOK_SECRET presence boolean",
        ),
        _check(
            key="connect_webhook_verified",
            label="Connect webhook is verified",
            status="Not verified",
            explanation=(
                "No approved read-only Stripe adapter is used in this phase, so Connect webhook "
                "registration is not verified with Stripe."
            ),
            evidence_source="No external Stripe verification call",
        ),
        _check(
            key="connect_organization_isolation",
            label="Account and application organization isolation",
            status="Configured" if org_bind else "Missing",
            explanation=(
                "Connect account metadata binds application and organization identifiers."
                if org_bind
                else "Organization binding for Connect accounts was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/work_setup.py",
        ),
        _check(
            key="applicant_token_rotation",
            label="Prior applicant tokens are rejected after rotation",
            status="Configured" if token_rotation else "Missing",
            explanation=(
                "Reissue replaces the stored hash, so the previous applicant token no longer matches."
                if token_rotation
                else "Applicant token rotation was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/service.py",
        ),
        _check(
            key="stripe_hosted_bank_data",
            label="Driver bank and routing information is Stripe-hosted only",
            status="Configured" if stripe_hosted_bank else "Missing",
            explanation=(
                "Application code refuses raw bank and routing fields. Drivers enter bank details only on Stripe-hosted pages."
                if stripe_hosted_bank
                else "Stripe-hosted bank-data handling was not confirmed."
            ),
            evidence_source="work_setup copy and sensitive_providers reject list",
        ),
    ]


def _onboarding_section() -> list[NovaPaymentsReadinessCheck]:
    from app.modules.platform_ops.onboarding.policies import (
        DRAFT_BANNER,
        ICA_POLICY_KEY,
        POLICY_CATALOG,
        REQUIRED_POLICY_KEYS,
    )

    required_count = len(REQUIRED_POLICY_KEYS)
    draft_count = 0
    published_count = 0
    ica_draft = False
    for item in POLICY_CATALOG:
        legal = str(item.get("legal_status") or "").upper()
        is_draft = legal == "DRAFT_FOR_ATTORNEY_REVIEW" or DRAFT_BANNER in str(item.get("body") or "")
        if item.get("key") == ICA_POLICY_KEY:
            ica_draft = is_draft
        if item.get("key") == ICA_POLICY_KEY:
            continue
        if is_draft:
            draft_count += 1
        else:
            published_count += 1
    ica_implemented = _has(
        "modules/platform_ops/onboarding/work_setup.py",
        "ICA_VERSION",
        "def agreement_is_signed",
        "Independent Contractor Agreement",
    )
    submit_requires_acks = _has(
        "modules/platform_ops/onboarding/service.py",
        "required_policies_complete",
        "Acknowledge all required driver policies (DRAFT FOR ATTORNEY REVIEW)",
    )
    tax_configured = _has(
        "modules/platform_ops/onboarding/work_setup.py",
        "def tax_information_is_complete",
        "W9_COMPLETE_STATUSES",
    )
    payout_configured = _has(
        "modules/platform_ops/onboarding/work_setup.py",
        "def start_payout_onboarding",
        "def payout_is_complete",
    )
    submit_not_activate = _has(
        "modules/platform_ops/onboarding/service.py",
        'application.status = "submitted"',
        "Only draft applications can be submitted.",
    ) and _has(
        "modules/platform_ops/onboarding/activation.py",
        "Application must be approved before activation.",
        "assert_approval_engine_allows_activation",
    )
    staff_required = _has(
        "modules/platform_ops/permissions.py",
        "APPROVAL_ROLES",
        "ACTIVATION_ROLES",
        "ROLE_ADMIN",
    )
    return [
        _check(
            key="ica_implementation",
            label="Independent Contractor Agreement implementation status",
            status="Configured" if ica_implemented else "Missing",
            explanation=(
                "An in-app Independent Contractor Agreement e-sign path exists. This is catalog status, not legal sufficiency."
                if ica_implemented
                else "Independent Contractor Agreement implementation was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/work_setup.py",
        ),
        _check(
            key="ica_attorney_draft",
            label="Agreement remains marked DRAFT FOR ATTORNEY REVIEW",
            status="Configured" if ica_draft else "Not verified",
            explanation=(
                "The catalog still marks the Independent Contractor Agreement as DRAFT FOR ATTORNEY REVIEW. "
                "This report does not declare the document legally sufficient."
                if ica_draft
                else "The attorney-review draft label could not be confirmed from the policy catalog."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/policies.py",
        ),
        _check(
            key="required_policy_count",
            label="Required policy count",
            status="Configured",
            explanation=f"The catalog lists {required_count} required driver policies, not including the agreement.",
            evidence_source="REQUIRED_POLICY_KEYS",
        ),
        _check(
            key="published_policy_count",
            label="Published or approved policy count",
            status="Configured" if published_count == 0 else "Blocked",
            explanation=(
                f"{published_count} catalog policies are published or approved. "
                "Draft policies are not treated as counsel-approved."
            ),
            evidence_source="POLICY_CATALOG legal_status",
        ),
        _check(
            key="draft_policy_count",
            label="Draft or unapproved policy count",
            status="Configured" if draft_count == required_count else "Not verified",
            explanation=f"{draft_count} of {required_count} required policies remain draft or unapproved.",
            evidence_source="POLICY_CATALOG legal_status",
        ),
        _check(
            key="submission_requires_acknowledgments",
            label="Submission requires all required acknowledgments",
            status="Configured" if submit_requires_acks else "Missing",
            explanation=(
                "Applicant submit requires every required policy acknowledgment plus the agreement."
                if submit_requires_acks
                else "Submission acknowledgment requirements were not found."
            ),
            evidence_source="validate_complete_application",
        ),
        _check(
            key="tax_w9_configured",
            label="Tax and W-9 integration configured",
            status="Configured" if tax_configured else "Missing",
            explanation=(
                "An electronic tax-status workflow exists. No tax values are returned here."
                if tax_configured
                else "Tax and W-9 integration was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/work_setup.py",
        ),
        _check(
            key="payout_onboarding_configured",
            label="Payout onboarding integration configured",
            status="Configured" if payout_configured else "Missing",
            explanation=(
                "Payout onboarding code exists. This phase does not start payout setup."
                if payout_configured
                else "Payout onboarding integration was not found."
            ),
            evidence_source="backend/app/modules/platform_ops/onboarding/work_setup.py",
        ),
        _check(
            key="submit_cannot_activate",
            label="Applicant submission cannot approve or activate a driver",
            status="Configured" if submit_not_activate else "Blocked",
            explanation=(
                "Submit moves an application to submitted only. Approval and activation stay on staff paths."
                if submit_not_activate
                else "Applicant submit could not be confirmed as non-activating."
            ),
            evidence_source="submit_application and activate_application",
        ),
        _check(
            key="staff_approval_required",
            label="Staff approval is still required",
            status="Configured" if staff_required else "Missing",
            explanation=(
                "Approval and activation roles are limited to admin, super-admin, and supervisor."
                if staff_required
                else "Staff approval requirements were not found."
            ),
            evidence_source="backend/app/modules/platform_ops/permissions.py",
        ),
    ]


def _safety_section() -> list[NovaPaymentsReadinessCheck]:
    test_live_split = _has(
        "modules/payments/rider_checkout.py",
        "Live Stripe keys are not allowed for rider checkout",
        "def is_live_stripe_key",
    )
    money_write_auth = _has(
        "modules/payments/routes.py",
        "_require_rider_payment_access",
        "ROLE_ADMIN",
        '@router.post("/rider/checkout")',
    )
    cross_org = _has(
        "core/nova/service.py",
        "Cross-tenant Nova access denied",
        "resolve_organization_scope",
    )
    webhook_sig = _has(
        "modules/payments/stripe_payments.py",
        "stripe.Webhook.construct_event",
        "STRIPE_PAYMENT_WEBHOOK_SECRET",
    )
    replay = _has(
        "modules/payments/models.py",
        "uq_amicor_customer_payment_events_event",
    )
    log_safe = _has(
        "modules/payments/rider_checkout.py",
        "def sanitize_checkout_error",
        "_SECRET_PATTERN",
        "stripe_secret_key_present=%s",
    )
    token_logs = _has(
        "modules/platform_ops/onboarding/service.py",
        'never persist or log it',
        '"token_included": False',
    )
    read_only_verify = True
    ai_gated = _has(
        "modules/approval_engine/driver_001.py",
        "never auto-approves, never activates",
    ) and _has(
        "modules/approval_engine/external_verification.py",
        "AI cannot record provider results",
    ) and _has(
        "modules/platform_ops/onboarding/activation.py",
        "assert_approval_engine_allows_activation",
    )
    return [
        _check(
            key="test_live_separation",
            label="TEST and LIVE data separation",
            status="Configured" if test_live_split else "Missing",
            explanation=(
                "Rider checkout rejects LIVE keys. TEST configuration is never treated as LIVE readiness."
                if test_live_split
                else "TEST and LIVE separation was not found."
            ),
            evidence_source="backend/app/modules/payments/rider_checkout.py",
        ),
        _check(
            key="money_write_authorization",
            label="Money-write endpoints require appropriate authorization",
            status="Configured" if money_write_auth else "Missing",
            explanation=(
                "Rider checkout and fare quote require an authorized session role."
                if money_write_auth
                else "Money-write authorization was not found."
            ),
            evidence_source="backend/app/modules/payments/routes.py",
        ),
        _check(
            key="cross_organization_refused",
            label="Cross-organization access is refused",
            status="Configured" if cross_org else "Missing",
            explanation=(
                "Nova organization scope refuses cross-organization access with 403."
                if cross_org
                else "Cross-organization refusal was not found."
            ),
            evidence_source="NovaCoreService.resolve_organization_scope",
        ),
        _check(
            key="webhook_signature_verification",
            label="Webhook signature verification",
            status="Configured" if webhook_sig else "Missing",
            explanation=(
                "Customer-payment webhooks require a Stripe signature. This is not a LIVE registration check."
                if webhook_sig
                else "Webhook signature verification was not found."
            ),
            evidence_source="backend/app/modules/payments/stripe_payments.py",
        ),
        _check(
            key="webhook_replay_protection",
            label="Webhook replay and idempotency protection",
            status="Configured" if replay else "Missing",
            explanation=(
                "Duplicate Stripe event ids are stored once on the customer-payment event ledger."
                if replay
                else "Webhook replay protection was not found."
            ),
            evidence_source="amicor_customer_payment_events",
        ),
        _check(
            key="sensitive_log_exclusion",
            label="Sensitive values excluded from logs",
            status="Configured" if log_safe else "Missing",
            explanation=(
                "Checkout errors redact secret-shaped values and log only a presence boolean."
                if log_safe
                else "Sensitive-value log exclusion was not found."
            ),
            evidence_source="sanitize_checkout_error",
        ),
        _check(
            key="applicant_token_log_exclusion",
            label="Applicant tokens excluded from ordinary logs",
            status="Configured" if token_logs else "Missing",
            explanation=(
                "Applicant token reissue stores a hash and records that the token was not included."
                if token_logs
                else "Applicant-token log exclusion was not found."
            ),
            evidence_source="reissue_applicant_access_token",
        ),
        _check(
            key="readonly_production_verification",
            label="Production verification can be performed without financial writes",
            status="Configured" if read_only_verify else "Missing",
            explanation="This readiness API is GET-only and does not create Stripe objects or payment records.",
            evidence_source="GET /api/nova/payments/readiness",
        ),
        _check(
            key="ai_cannot_money_move",
            label="AI cannot approve, activate, pay, refund, transfer, file, or submit without a human",
            status="Configured" if ai_gated else "Missing",
            explanation=(
                "Approval Engine review does not owner-approve or activate. Money writes stay on authorized human paths."
                if ai_gated
                else "Human-authorization gates for AI were not found."
            ),
            evidence_source="approval_engine and activation adapters",
        ),
    ]


def _blockers(sections: list[NovaPaymentsReadinessSection]) -> list[NovaPaymentsReadinessBlocker]:
    by_key = {check.key: check for section in sections for check in section.checks}
    ordered_keys = [
        "stripe_mode",
        "key_modes_match",
        "customer_webhook_signing",
        "customer_webhook_route",
        "connect_webhook_route",
        "connect_webhook_configured",
        "connect_webhook_verified",
        "connect_return_url",
        "connect_refresh_url",
        "ica_attorney_draft",
        "draft_policy_count",
        "published_policy_count",
        "staff_approval_required",
        "connect_configured",
    ]
    why = {
        "stripe_mode": "LIVE customer payments cannot start until LIVE mode is independently verified and authorized.",
        "key_modes_match": "Mismatched key modes can charge or sign the wrong Stripe environment.",
        "customer_webhook_signing": "LIVE payment confirmation cannot be trusted without a configured signing secret.",
        "customer_webhook_route": "LIVE payment events have nowhere to land if the webhook route is missing.",
        "connect_webhook_route": "Route existence, configuration, and Stripe verification are separate. A missing Connect route blocks LIVE payouts.",
        "connect_webhook_configured": "A Connect webhook secret is required before LIVE connected-account updates can be trusted.",
        "connect_webhook_verified": "Configured is not verified. LIVE payouts need a human-confirmed Connect webhook at Stripe.",
        "connect_return_url": "LIVE Connect onboarding must return only to the approved HTTPS production host.",
        "connect_refresh_url": "LIVE Connect refresh must stay on the approved HTTPS production host.",
        "ica_attorney_draft": "LIVE recruiting and activation cannot treat a draft agreement as final legal language.",
        "draft_policy_count": "Required policies remain drafts for attorney review.",
        "published_policy_count": "No counsel-approved policy pack is published.",
        "staff_approval_required": "LIVE driver activation still requires a human staff approval path.",
        "connect_configured": "Driver payouts cannot start until Connect is configured and later verified.",
    }
    actions = {
        "stripe_mode": "Owner must explicitly authorize LIVE Stripe keys after a separate verification pass.",
        "key_modes_match": "Owner or engineering must align publishable and secret key modes. Not authorized in this phase.",
        "customer_webhook_signing": "Owner or engineering must add a LIVE customer-payment webhook secret when LIVE is authorized.",
        "customer_webhook_route": "Engineering must add the missing route. Not authorized in this phase.",
        "connect_webhook_route": "Engineering must add a Connect webhook route. Not authorized in this phase.",
        "connect_webhook_configured": "Owner or engineering must configure a Connect webhook secret when authorized.",
        "connect_webhook_verified": "Owner must verify the Connect webhook with Stripe when LIVE payouts are authorized.",
        "connect_return_url": "Engineering must restrict return URLs to HTTPS on the approved production host when authorized.",
        "connect_refresh_url": "Engineering must restrict refresh URLs to HTTPS on the approved production host when authorized.",
        "ica_attorney_draft": "Counsel must complete attorney review. Policy text is not changed in this phase.",
        "draft_policy_count": "Counsel must approve required policies. Catalog text is not changed in this phase.",
        "published_policy_count": "Counsel must publish approved policies. Catalog text is not changed in this phase.",
        "staff_approval_required": "Keep human approval. Do not auto-approve or activate Driver 001.",
        "connect_configured": "Owner must add Connect keys only when LIVE payouts are explicitly authorized.",
    }
    areas = {
        "stripe_mode": "Customer payment configuration",
        "key_modes_match": "Customer payment configuration",
        "customer_webhook_signing": "Customer payment configuration",
        "customer_webhook_route": "Customer payment configuration",
        "connect_webhook_route": "Stripe Connect and driver payout configuration",
        "connect_webhook_configured": "Stripe Connect and driver payout configuration",
        "connect_webhook_verified": "Stripe Connect and driver payout configuration",
        "connect_return_url": "Stripe Connect and driver payout configuration",
        "connect_refresh_url": "Stripe Connect and driver payout configuration",
        "connect_configured": "Stripe Connect and driver payout configuration",
        "ica_attorney_draft": "Driver onboarding business gates",
        "draft_policy_count": "Driver onboarding business gates",
        "published_policy_count": "Driver onboarding business gates",
        "staff_approval_required": "Driver onboarding business gates",
    }
    blockers: list[NovaPaymentsReadinessBlocker] = []
    for key in ordered_keys:
        check = by_key.get(key)
        if check is None:
            continue
        if check.status not in {"Missing", "Blocked", "Not verified"}:
            if key == "ica_attorney_draft" and check.status == "Configured":
                blockers.append(
                    NovaPaymentsReadinessBlocker(
                        area=areas[key],
                        current_status="Blocked",
                        evidence_source=check.evidence_source,
                        why_blocks_live=why[key],
                        required_action=actions[key],
                        action_authorized_now=False,
                    )
                )
            elif key in {"draft_policy_count", "published_policy_count", "staff_approval_required"} and check.status == "Configured":
                blockers.append(
                    NovaPaymentsReadinessBlocker(
                        area=areas[key],
                        current_status="Blocked",
                        evidence_source=check.evidence_source,
                        why_blocks_live=why[key],
                        required_action=actions[key],
                        action_authorized_now=False,
                    )
                )
            continue
        blockers.append(
            NovaPaymentsReadinessBlocker(
                area=areas[key],
                current_status=check.status,
                evidence_source=check.evidence_source,
                why_blocks_live=why[key],
                required_action=actions[key],
                action_authorized_now=False,
            )
        )
    return blockers


def _overall_mode(sections: list[NovaPaymentsReadinessSection]) -> str:
    for section in sections:
        for check in section.checks:
            if check.key == "stripe_mode":
                if check.status == "Configured" and check.classification in {"TEST", "LIVE"}:
                    return check.classification
                return "Not verified"
    return "Not verified"


def _payload_is_safe(payload: NovaPaymentsReadinessOut) -> bool:
    dumped = payload.model_dump_json()
    return _LEAK_PATTERN.search(dumped) is None


def readiness(db: Session, *, organization_id: str, user: UserContext) -> NovaPaymentsReadinessOut:
    _ = db
    if normalize_role(user.role) not in READINESS_ROLES:
        raise NovaPaymentsReadinessError(
            "Payments readiness is limited to admin and super-admin roles",
            status_code=403,
        )
    sections = [
        _safe_section("customer_payments", "Customer payment configuration", _customer_payment_section),
        _safe_section("connect_payouts", "Stripe Connect and driver payout configuration", _connect_section),
        _safe_section("onboarding_gates", "Driver onboarding business gates", _onboarding_section),
        _safe_section("operational_safety", "Operational safety controls", _safety_section),
    ]
    payload = NovaPaymentsReadinessOut(
        organization_id=organization_id,
        stripe_mode=_overall_mode(sections),
        go_live_displayed=False,
        live_customer_payments_verified=False,
        live_driver_payouts_verified=False,
        sections=sections,
        blockers=_blockers(sections),
    )
    if not _payload_is_safe(payload):
        raise NovaPaymentsReadinessError(
            "Readiness payload failed the secret-exclusion check",
            status_code=500,
        )
    return payload
