"""Test that future casting API payloads exclude private storage and identity fields."""
import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/casting_responses.py"


def test_allowlisted_application_and_media_responses():
    spec = importlib.util.spec_from_file_location("casting_responses_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = {
        "id": "application-1", "campaign_id": "campaign-1", "status": "DRAFT",
        "created_at": "2026-10-10", "applicant_id": "person-secret",
        "owner_id": "org-secret", "consent_version": "v1", "storage_key": "private/blob",
        "signed_url": "https://private.example/file", "application_id": "application-1",
        "mime_type": "video/mp4", "byte_size": 123,
    }
    for projector in (module.applicant_application_view, module.organizer_application_view, module.media_status_view):
        result = projector(data)
        for forbidden in ("storage_key", "signed_url", "owner_id", "applicant_id", "consent_version"):
            assert forbidden not in result
    assert module.media_status_view(data)["status"] == "DRAFT"
    campaign = module.campaign_public_view({
        **data, "title": "Draft", "category": "film", "minimum_age": 18,
    })
    assert campaign["minimum_age"] == 18
    assert "owner_id" not in campaign
    assert "storage_key" not in campaign
