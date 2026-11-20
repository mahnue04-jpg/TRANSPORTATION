"""Safety tests for isolated Operations Stripe TEST gateway.

No Stripe network, real customers, or production DB is accessed.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _import_sandbox(**changes):
    env = dict(os.environ)
    # Do not inherit the CI runner database location.
    env.pop("DATABASE_URL", None)
    env.update({
        "NOVA_OPERATIONS_SANDBOX_ENABLED": "true",
        "NOVA_OPERATIONS_SANDBOX_DB_URL": "sqlite:////tmp/amicor-operations-sandbox-ci-check.sqlite",
        "STRIPE_SECRET_KEY": "sk_test_synthetic_ci_only",
        "STRIPE_NOVA_AGENT_WEBHOOK_SECRET": "whsec_synthetic_ci_only",
        "NOVA_OPERATIONS_STARTER_TEST_PRICE_ID": "price_ci_synthetic",
        "APP_ENV": "staging",
        "AMICOR_ENVIRONMENT": "staging",
        "NOVA_STRIPE_LIVE_ENABLED": "false",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "false",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED": "false",
        "NOVA_OPERATIONS_OWNER_CSV_ENABLED": "false",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED": "false",
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED": "false",
        "NOVA_OPERATIONS_STARTER_BINDING_ENABLED": "false",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED": "false",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED": "false",
    })
    env.update(changes)
    return subprocess.run(
        [sys.executable, "-c", "import operations_checkout_sandbox as sandbox; print('SANDBOX_IMPORTED')"],
        cwd=str(BACKEND_DIR),
        env=env, capture_output=True, text=True, timeout=45,
    )


def test_sandbox_imports_without_full_application():
    completed = _import_sandbox()
    assert completed.returncode == 0, completed.stderr[-1800:]
    assert "SANDBOX_IMPORTED" in completed.stdout


def test_sandbox_accepts_restricted_test_stripe_key():
    completed = _import_sandbox(STRIPE_SECRET_KEY="rk_test_synthetic_ci_only")
    assert completed.returncode == 0, completed.stderr[-1800:]
    assert "SANDBOX_IMPORTED" in completed.stdout


def test_sandbox_rejects_restricted_live_stripe_key():
    completed = _import_sandbox(STRIPE_SECRET_KEY="rk_live_synthetic_ci_only")
    assert completed.returncode != 0
    assert "sandbox requires isolated SQLite" in completed.stderr


def test_sandbox_rejects_live_stripe_key():
    completed = _import_sandbox(STRIPE_SECRET_KEY="sk_live_synthetic_ci_only")
    assert completed.returncode != 0
    assert "sandbox requires isolated SQLite" in completed.stderr


def test_sandbox_rejects_production_database():
    completed = _import_sandbox(DATABASE_URL="postgresql://example.invalid/test")
    assert completed.returncode != 0
    assert "DATABASE_URL mismatch" in completed.stderr


def test_sandbox_rejects_durable_receipt_mode():
    completed = _import_sandbox(NOVA_OPERATIONS_DURABLE_RECEIPT_ENABLED="true")
    assert completed.returncode != 0
    assert "sandbox requires isolated SQLite" in completed.stderr


def test_sandbox_rejects_customer_processing_switch():
    completed = _import_sandbox(NOVA_OPERATIONS_DURABLE_CSV_ENABLED="true")
    assert completed.returncode != 0
    assert "sandbox requires isolated SQLite" in completed.stderr


def test_owner_test_page_contains_no_embedded_credentials():
    page = (BACKEND_DIR / "operations_checkout_sandbox_ui.html").read_text(encoding="utf-8")
    assert "Create synthetic $49 checkout" in page
    assert "x-amicor-sandbox-token" in page
    assert "sk_test_" not in page
    assert "rk_test_" not in page
    assert "whsec_" not in page
    assert "https://checkout.stripe.com/" in page


def test_sandbox_return_page_never_uses_query_as_payment_proof():
    source = (BACKEND_DIR / "operations_checkout_sandbox.py").read_text(encoding="utf-8")
    assert 'path == "/nova/anonymous-agent"' in source
    assert 'outcome in {"success", "cancelled"}' in source
    assert "only the signed webhook updates DB" in source
    assert "Payment confirmation is handled separately" in source
