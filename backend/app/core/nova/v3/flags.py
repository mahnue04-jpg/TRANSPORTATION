"""Nova V3 live flags. Production defaults remain OFF unless explicitly enabled.

Discovery and controlled submission flags are read from the environment at call
time so a process never caches a stale OFF after the owner enables the flag.
"""

import os

_TRUE = {"1", "true", "yes", "on"}


def _env_enabled(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in _TRUE


def live_discovery_enabled() -> bool:
    return _env_enabled("NOVA_V3_LIVE_DISCOVERY_ENABLED")


def external_submission_enabled() -> bool:
    return _env_enabled("NOVA_V3_EXTERNAL_SUBMISSION_ENABLED")


# Back-compat module attributes. Prefer the callables / live_flags() at runtime.
LIVE_DISCOVERY_ENABLED = live_discovery_enabled()
EXTERNAL_SUBMISSION_ENABLED = external_submission_enabled()
CLIENT_CONTACT_ENABLED = False
REPORT_SEND_ENABLED = False
INVOICE_SEND_ENABLED = False
FINANCIAL_EXECUTION_ENABLED = False
BACKGROUND_WORKER_ENABLED = False
LIVE_CONNECTORS_ENABLED = False
EXTERNAL_WEBHOOK_PROCESSING_ENABLED = False
PROCESSOR_APPLY_TO_LEDGER = False


def live_flags() -> dict[str, bool]:
    discovery = live_discovery_enabled()
    submission = external_submission_enabled()
    return {
        "LIVE_DISCOVERY_ENABLED": discovery,
        "EXTERNAL_SUBMISSION_ENABLED": submission,
        "CLIENT_CONTACT_ENABLED": CLIENT_CONTACT_ENABLED,
        "REPORT_SEND_ENABLED": REPORT_SEND_ENABLED,
        "INVOICE_SEND_ENABLED": INVOICE_SEND_ENABLED,
        "FINANCIAL_EXECUTION_ENABLED": FINANCIAL_EXECUTION_ENABLED,
        "BACKGROUND_WORKER_ENABLED": BACKGROUND_WORKER_ENABLED,
        "LIVE_CONNECTORS_ENABLED": LIVE_CONNECTORS_ENABLED,
        "EXTERNAL_WEBHOOK_PROCESSING_ENABLED": EXTERNAL_WEBHOOK_PROCESSING_ENABLED,
        "PROCESSOR_APPLY_TO_LEDGER": PROCESSOR_APPLY_TO_LEDGER,
        "APPROVED_EQUALS_EXECUTED": False,
        "APPROVED_EQUALS_SUBMITTED": False,
        "COMPLETE_EQUALS_PAID": False,
        "HEADER_CAN_ENABLE_LIVE": False,
        "TEXT_CAN_ENABLE_LIVE": False,
        "MOCK_TRANSPORT_ONLY": True,
        "LIVE_DISCOVERY": discovery,
        "REAL_EXTERNAL_SUBMISSION": submission,
        "REAL_CLIENT_CONTACT": False,
        "REAL_EMAIL_SEND": False,
        "REAL_INVOICE_SEND": False,
        "REAL_FINANCIAL_EXECUTION": False,
        "REAL_BACKGROUND_WORKER": False,
        "REAL_CONNECTORS": False,
        "REAL_WEBHOOK_PUBLIC_ENDPOINT": False,
        "LIVE_LEAD_DISCOVERY": False,
        "REAL_OUTREACH_SEND": False,
        "REAL_SMS_SEND": False,
        "REAL_SOCIAL_POST": False,
        "REAL_AD_SPEND": False,
        "REAL_CALENDAR_WRITE": False,
        "REAL_PROPOSAL_SEND": False,
        "REAL_CONTRACT_ACCEPTANCE": False,
        "REAL_PAYMENT_EXECUTION": False,
    }
