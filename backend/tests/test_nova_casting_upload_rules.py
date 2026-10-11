"""Standalone tests for inactive audition upload metadata rules."""
import importlib.util
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/casting_upload_rules.py"
spec = importlib.util.spec_from_file_location("casting_upload_rules_test_module", PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_upload_metadata_rejects_missing_consent_and_invalid_files():
    valid = dict(mime_type="video/mp4", byte_size=1024, consent_confirmed=True)
    assert module.validate_audition_upload_metadata(**valid).allowed
    for override in (
        {"consent_confirmed": False},
        {"mime_type": "image/jpeg"},
        {"byte_size": 0},
        {"byte_size": -10},
        {"byte_size": True},
        {"byte_size": 251 * 1024 * 1024},
    ):
        payload = {**valid, **override}
        assert not module.validate_audition_upload_metadata(**payload).allowed


def test_upload_rules_do_not_activate_media_service():
    source = PATH.read_text(encoding="utf-8")
    assert "UploadDecision" in source
    assert "MAX_VIDEO_BYTES" in source
    assert "upload_file" not in source
    assert "boto3" not in source
