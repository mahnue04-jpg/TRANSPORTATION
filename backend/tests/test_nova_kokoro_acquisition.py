"""Acquisition requires an explicit download flag and pinned revision."""
from pathlib import Path
import pytest
from acquire_kokoro import acquire, FILES, REPOSITORY


def test_dry_run_does_not_create_files(tmp_path: Path):
    dest = tmp_path / "kokoro"
    result = acquire(destination=dest)
    assert result["repository"] == REPOSITORY
    assert result["files"] == list(FILES)
    assert result["downloaded"] is False
    assert not dest.exists()


def test_download_requires_revision_before_install(tmp_path: Path):
    with pytest.raises(ValueError, match="reviewed commit hash"):
        acquire(destination=tmp_path / "model", download=True)
    with pytest.raises(ValueError, match="40-character"):
        acquire(destination=tmp_path / "model", download=True, revision="main")


def test_existing_destination_never_overwritten(tmp_path: Path):
    dest = tmp_path / "model"
    dest.mkdir()
    sentinel = dest / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        acquire(destination=dest, download=True, revision="a" * 40)
    assert sentinel.read_text(encoding="utf-8") == "keep"
