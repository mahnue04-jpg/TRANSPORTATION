from pathlib import Path

import pytest

from app.core.nova.marketplace import service


def test_approved_file_must_match_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setenv("AMICOR_MARKETPLACE_PRIVATE_DIR", str(tmp_path))
    with pytest.raises(service.MarketplaceFileError):
        service.store_verified_pdf("ai-side-income-checklist", b"%PDF-not-the-approved-file")


def test_unknown_product_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("AMICOR_MARKETPLACE_PRIVATE_DIR", str(tmp_path))
    with pytest.raises(service.MarketplaceFileError):
        service.product_path("not-a-real-product")


def test_status_fails_closed_without_private_storage(monkeypatch):
    monkeypatch.delenv("AMICOR_MARKETPLACE_PRIVATE_DIR", raising=False)
    status = service.verified_file_status("ai-side-income-checklist")
    assert status["configured"] is False
    assert status["verified"] is False


def test_paid_product_is_marked_paid():
    spec = service.product_spec("ai-automation-blueprint")
    assert spec["access"] == "paid"
    assert spec["price_cents"] == 2900
