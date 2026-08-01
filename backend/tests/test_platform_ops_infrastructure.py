"""Infrastructure tests for Phase 53 — migrations and document storage."""
from __future__ import annotations

import io
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_head_on_clean_sqlite() -> None:
    db_path = BACKEND_ROOT / "data" / f"test_alembic_clean_{uuid4().hex}.db"
    if db_path.exists():
        db_path.unlink()
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    try:
        assert result.returncode == 0, result.stderr or result.stdout
    finally:
        if db_path.exists():
            db_path.unlink()


def test_render_disk_storage_roundtrip() -> None:
    from app.modules.platform_ops.storage import RenderDiskDocumentStorage

    with tempfile.TemporaryDirectory() as tmp:
        storage = RenderDiskDocumentStorage(base_dir=Path(tmp))
        payload = b"render-disk-roundtrip"
        _, ref, size = storage.store(
            organization_id="org-1",
            application_id="app-1",
            category="drivers_license_front",
            filename="id.pdf",
            content_type="application/pdf",
            stream=io.BytesIO(payload),
        )
        assert size == len(payload)
        retrieved, _ = storage.retrieve(storage_ref=ref)
        assert retrieved == payload
        storage.delete(storage_ref=ref)
        with pytest.raises(FileNotFoundError):
            storage.retrieve(storage_ref=ref)
