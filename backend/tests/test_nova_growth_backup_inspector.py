"""Synthetic-only tests for read-only Growth Agent backup archive inspection."""
from __future__ import annotations

import io
import tarfile

import pytest
from scripts.inspect_growth_backup import inspect_archive


def _archive(path, members):
    with tarfile.open(path, "w:gz") as tar:
        for name, body in members:
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_directory_dump_wrapper_is_identified_without_restore(tmp_path):
    path = tmp_path / "synthetic.tar.gz"
    _archive(path, [("export/toc.dat", "synthetic table of contents"), ("export/0001.dat.gz", "synthetic data")])
    result = inspect_archive(path)
    assert result["toc_dat_present"] is True
    assert result["postgres_restore_verified"] is False
    assert result["structural_inspection_only"] is True
    assert result["member_count"] == 2
    assert len(result["sha256"]) == 64


def test_unknown_tar_is_not_misrepresented_as_restorable(tmp_path):
    path = tmp_path / "unknown.tar.gz"
    _archive(path, [("notes.txt", "not a pg dump")])
    result = inspect_archive(path)
    assert result["toc_dat_present"] is False
    assert result["postgres_restore_verified"] is False


@pytest.mark.parametrize("unsafe", ["../escape.txt", "/absolute.txt", "folder/../escape.txt"])
def test_path_traversal_is_rejected(tmp_path, unsafe):
    path = tmp_path / "unsafe.tar.gz"
    _archive(path, [(unsafe, "never extract")])
    with pytest.raises(ValueError, match="Unsafe archive"):
        inspect_archive(path)


def test_missing_archive_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        inspect_archive(tmp_path / "missing.tar.gz")
