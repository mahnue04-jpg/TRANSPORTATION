"""Private on-disk bytes for scanned audition videos.

Files stay outside static hosting and Creative Studio's public media mount.
Keys are opaque ids. This module does not create signed URLs.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_KEY = re.compile(r"^[a-f0-9]{32}$")
_TX_KEY = "nova_casting_private_media_tx"


class PrivateMediaTransaction:
    """Files written in a request are removed if the database commit fails.

    Files released by withdrawal are removed only after the commit succeeds.
    The transaction lives on the SQLAlchemy session so it survives FastAPI's
    thread handoff.
    """

    def __init__(self) -> None:
        self.rollback_keys: list[str] = []
        self.commit_keys: list[str] = []


def media_transaction(db) -> PrivateMediaTransaction:
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return PrivateMediaTransaction()
    current = info.get(_TX_KEY)
    if isinstance(current, PrivateMediaTransaction):
        return current
    current = PrivateMediaTransaction()
    info[_TX_KEY] = current
    return current


def note_private_file_written(db, storage_key: str) -> None:
    if isinstance(storage_key, str) and _KEY.fullmatch(storage_key):
        media_transaction(db).rollback_keys.append(storage_key)


def note_private_file_release(db, storage_key: str) -> None:
    if isinstance(storage_key, str) and _KEY.fullmatch(storage_key):
        media_transaction(db).commit_keys.append(storage_key)


def finish_private_media_transaction(db, *, committed: bool) -> None:
    info = getattr(db, "info", None)
    transaction = info.get(_TX_KEY) if isinstance(info, dict) else None
    if not isinstance(transaction, PrivateMediaTransaction):
        return
    for storage_key in (transaction.commit_keys if committed else transaction.rollback_keys):
        delete_private_file(storage_key)


def _public_roots() -> list[Path]:
    backend = Path(__file__).resolve().parents[4]
    roots = [backend / "static"]
    creative = str(os.getenv("NOVA_CREATIVE_MEDIA_DIR") or "").strip()
    if creative:
        roots.append(Path(creative))
    roots.append(Path("/data/onboarding_docs/nova_creative_media"))
    return roots


def _overlaps_public(resolved: Path) -> bool:
    for public_root in _public_roots():
        public = public_root.resolve()
        if resolved == public or public in resolved.parents or resolved in public.parents:
            return True
    return False


def private_media_root() -> Path:
    configured = str(os.getenv("NOVA_CASTING_PRIVATE_MEDIA_DIR") or "").strip()
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / "nova-casting-private-media"
    resolved = root.resolve()
    if _overlaps_public(resolved):
        raise RuntimeError("Casting media directory must stay private")
    resolved.mkdir(parents=True, exist_ok=True)
    os.chmod(resolved, 0o700)
    return resolved


def write_private_file(media_id: str, data: bytes) -> str:
    if not _KEY.fullmatch(media_id):
        raise ValueError("Invalid media id")
    path = private_media_root() / media_id
    path.write_bytes(data)
    os.chmod(path, 0o600)
    return media_id


def read_private_file(storage_key: str) -> bytes | None:
    if not isinstance(storage_key, str) or not _KEY.fullmatch(storage_key):
        return None
    root = private_media_root()
    path = (root / storage_key).resolve()
    if path.parent != root or not path.is_file():
        return None
    return path.read_bytes()


def private_file_exists(storage_key: str) -> bool:
    if not isinstance(storage_key, str) or not _KEY.fullmatch(storage_key):
        return False
    root = private_media_root()
    path = (root / storage_key).resolve()
    return path.parent == root and path.is_file()


def delete_private_file(storage_key: str) -> None:
    if not isinstance(storage_key, str) or not _KEY.fullmatch(storage_key):
        return
    root = private_media_root()
    path = (root / storage_key).resolve()
    if path.parent == root and path.is_file():
        path.unlink()


def delete_unreferenced_private_files(referenced_keys: set[str]) -> int:
    """Remove private files that no CLEAN row still names. The directory is exclusive."""
    root = private_media_root()
    removed = 0
    for path in list(root.iterdir()):
        if not path.is_file():
            continue
        if not _KEY.fullmatch(path.name) or path.name not in referenced_keys:
            path.unlink()
            removed += 1
    return removed
