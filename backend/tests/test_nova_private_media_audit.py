"""Private-media inventory audits metadata without touching media files."""
from types import SimpleNamespace

from app.core.nova.creative_studio.private_media_audit import audit_protected_media


def asset(url, *, source=None, approved=False):
    return SimpleNamespace(url=url, metadata={"source": source, "approved_master": approved})


def test_classifies_legacy_sources_and_approved_masters_without_exposing_paths():
    rows = [
        asset("/media/nova-creative/old.mp4", source="owner_video_import"),
        asset("/static/generated/nova-creative/older.mp4", source="owner_import"),
        asset("/assets/master.mp4", approved=True),
        asset("private-media://imported_video_abcdef123456.mp4", source="owner_video_import"),
        asset(None, source="owner_import"),
        asset("/media/nova-creative/disposable.mp4", source="generated_preview"),
    ]
    assert audit_protected_media(rows) == {
        "protected_total": 5,
        "private_reference": 1,
        "public_reference_requires_migration": 3,
        "missing_reference_requires_review": 1,
    }


def test_audit_is_read_only_and_does_not_read_asset_files(tmp_path):
    original = tmp_path / "original.mp4"
    original.write_bytes(b"original-unchanged")
    result = audit_protected_media([asset("/media/nova-creative/original.mp4", approved=True)])
    assert result["public_reference_requires_migration"] == 1
    assert result["private_reference"] == 0
    assert original.read_bytes() == b"original-unchanged"
    assert tuple(tmp_path.iterdir()) == (original,)
