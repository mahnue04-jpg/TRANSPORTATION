"""Draft intake validation never stores uploads or accepts minors."""
import importlib.util
import sys
import types
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"


def load():
    prefix = "_casting_intake_schema_test"
    package = types.ModuleType(prefix)
    package.__path__ = [str(FOLDER)]
    sys.modules[prefix] = package
    for name in ("casting_upload_rules", "casting_intake_schema"):
        spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", FOLDER / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{prefix}.casting_intake_schema"]


def test_application_intake_requires_adult_consent_and_private_video_metadata():
    schema = load()
    valid = dict(consent_accepted=True, consent_version="v1", age_years=21, mime_type="video/mp4", byte_size=2048)
    assert schema.validate_draft_application_intake(valid).accepted
    for override in (
        {"consent_accepted": False},
        {"age_years": 17},
        {"age_years": True},
        {"mime_type": "image/jpeg"},
        {"byte_size": 0},
        {"consent_version": ""},
    ):
        decision = schema.validate_draft_application_intake({**valid, **override})
        assert not decision.accepted
    guarded = {**valid, "age_years": 16, "guardian_attestation": True}
    assert not schema.validate_draft_application_intake(guarded).accepted
    scored = {**valid, "facial_score": 0.9}
    assert schema.validate_draft_application_intake(scored).reason == "Unsupported field"


def test_campaign_spec_cannot_publish_or_lower_the_age_floor():
    schema = load()
    decision = schema.validate_draft_campaign(
        {"title": "City film", "category": "film", "minimum_age": 18, "status": "DRAFT"}
    )
    assert decision.accepted
    assert not schema.validate_draft_campaign(
        {"title": "Open call", "category": "film", "minimum_age": 18, "status": "OPEN"}
    ).accepted
    assert not schema.validate_draft_campaign(
        {"title": "Youth", "category": "beauty", "minimum_age": 13, "status": "DRAFT"}
    ).accepted
    source = (FOLDER / "casting_intake_schema.py").read_text(encoding="utf-8")
    assert "boto3" not in source
    assert "upload_file" not in source
