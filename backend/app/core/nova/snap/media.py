"""Private capture bytes. Files stay outside /static and have no public URL."""
import os
import re
from pathlib import Path

from fastapi import HTTPException

_KEY = re.compile(r"^[a-f0-9]{32}$")


def media_root() -> Path:
    raw = os.getenv("SNAP_MEDIA_DIR", "").strip()
    if raw:
        root = Path(raw)
    else:
        root = Path(__file__).resolve().parents[4] / "data" / "snap-private"
    root.mkdir(parents=True, exist_ok=True)
    return root


def path_for(storage_key: str) -> Path:
    if not _KEY.fullmatch(storage_key or ""):
        raise HTTPException(404, "Capture not found.")
    root = media_root().resolve()
    path = (root / storage_key).resolve()
    if path.parent != root:
        raise HTTPException(404, "Capture not found.")
    return path


def write_bytes(storage_key: str, data: bytes) -> None:
    path = path_for(storage_key)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def read_path(storage_key: str) -> Path:
    path = path_for(storage_key)
    if not path.is_file():
        raise HTTPException(404, "Capture not found.")
    return path


def delete_bytes(storage_key: str) -> None:
    path = path_for(storage_key)
    if path.is_file():
        path.unlink()
