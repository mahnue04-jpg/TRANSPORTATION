"""Synthetic-only startup and route checks for isolated Operations validation."""
import pytest
from fastapi.testclient import TestClient

from operations_isolated_validation import app


def test_isolated_health_and_disabled_customer_csv(monkeypatch):
    for flag in (
        "NOVA_OPERATIONS_OWNER_CSV_ENABLED",
        "NOVA_OPERATIONS_STARTER_BINDING_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
        "NOVA_STRIPE_LIVE_ENABLED",
    ):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["synthetic_only"] is True
        assert response.json()["customer_processing"] is False
        assert response.json()["full_app_startup"] is False
        assert client.post("/api/nova/work/operations/csv-clean").status_code == 503
        assert client.post("/api/nova/work/operations/eligible-csv-tasks").status_code == 503


@pytest.mark.parametrize("flag", [
    "NOVA_OPERATIONS_OWNER_CSV_ENABLED",
    "NOVA_OPERATIONS_STARTER_BINDING_ENABLED",
    "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
    "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
    "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
    "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
    "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED",
    "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
    "NOVA_STRIPE_LIVE_ENABLED",
])
def test_isolated_startup_fails_when_any_live_or_processing_flag_enabled(
    monkeypatch, flag
):
    for key in (
        "NOVA_OPERATIONS_OWNER_CSV_ENABLED",
        "NOVA_OPERATIONS_STARTER_BINDING_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
        "NOVA_STRIPE_LIVE_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    monkeypatch.setenv(flag, "true")
    with pytest.raises(RuntimeError, match="prohibits live or processing flags"):
        with TestClient(app):
            pass


def test_diagnostic_denies_processing_after_runtime_config_drift(monkeypatch):
    for flag in (
        "NOVA_OPERATIONS_OWNER_CSV_ENABLED",
        "NOVA_OPERATIONS_STARTER_BINDING_ENABLED",
        "NOVA_OPERATIONS_DURABLE_CSV_ENABLED",
        "NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED",
        "NOVA_OPERATIONS_LEASE_WORKER_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED",
        "NOVA_WORK_REVENUE_PRIVATE_STORAGE_ENABLED",
        "NOVA_STRIPE_LIVE_ENABLED",
    ):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    with TestClient(app) as client:
        monkeypatch.setenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "true")
        response = client.get("/health")
        assert response.status_code == 503
        denied = client.post(
            "/api/nova/work/operations/engagements/eng/tasks/task/csv-clean",
            content=b"name\\nSample\\n",
            headers={"Content-Type": "text/csv"},
        )
        assert denied.status_code == 503
