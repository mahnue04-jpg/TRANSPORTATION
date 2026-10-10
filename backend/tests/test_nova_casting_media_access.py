"""Standalone tests for scanned, organization-scoped media metadata."""
import importlib.util
import sys
import types
from pathlib import Path
import pytest

FOLDER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"


def load():
    prefix = "_casting_media_access_tests"
    package = types.ModuleType(prefix)
    package.__path__ = [str(FOLDER)]
    sys.modules[prefix] = package
    for name in ("casting_policy", "casting_workflow_policy", "casting_responses", "casting_access", "casting_media_access"):
        spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", FOLDER / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{prefix}.casting_policy"], sys.modules[f"{prefix}.casting_media_access"]


def test_media_requires_clean_status_matching_application_and_organization():
    policy, access = load()
    reviewer = policy.CastingActor("reviewer", "org1", policy.CastingRole.REVIEWER, True)
    app = {"id": "app1", "applicant_id": "talent1", "campaign_id": "camp1", "owner_id": "org1"}
    campaign = {"id": "camp1", "owner_id": "org1"}
    media = {"id": "media1", "application_id": "app1", "owner_id": "org1",
             "status": "CLEAN", "mime_type": "video/mp4", "byte_size": 2048,
             "storage_key": "never-expose-private-location"}
    assert "storage_key" not in access.read_media_metadata(actor=reviewer, application=app, campaign=campaign, media=media)
    cases = [
        {**media, "status": "PENDING"},
        {**media, "status": "QUARANTINED"},
        {**media, "application_id": "other"},
        {**media, "owner_id": "other"},
    ]
    for invalid in cases:
        with pytest.raises(access.CastingAccessDenied):
            access.read_media_metadata(actor=reviewer, application=app, campaign=campaign, media=invalid)
    outsider = policy.CastingActor("outsider", "org2", policy.CastingRole.REVIEWER, True)
    with pytest.raises(access.CastingAccessDenied):
        access.read_media_metadata(actor=outsider, application=app, campaign=campaign, media=media)
