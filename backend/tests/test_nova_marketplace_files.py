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


def test_storage_root_falls_back_to_existing_render_disk(monkeypatch, tmp_path):
    monkeypatch.delenv("AMICOR_MARKETPLACE_PRIVATE_DIR", raising=False)
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE", "render_disk")
    monkeypatch.setenv("PLATFORM_OPS_DOCUMENT_STORAGE_PATH", str(tmp_path))
    root = service.storage_root()
    assert root == (tmp_path / "marketplace_products").resolve()
    assert root.is_dir()
