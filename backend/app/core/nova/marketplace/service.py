"""Private file storage and verification for AMICOR marketplace deliverables."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .manifest import PRODUCT_FILES

MAX_PRODUCT_FILE_BYTES = 10 * 1024 * 1024


class MarketplaceFileError(Exception):
    pass


def storage_root() -> Path:
    raw = (os.getenv("AMICOR_MARKETPLACE_PRIVATE_DIR") or "").strip()
    if not raw:
        raise MarketplaceFileError("AMICOR_MARKETPLACE_PRIVATE_DIR is not configured.")
    root = Path(raw).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def product_spec(slug: str) -> dict:
    spec = PRODUCT_FILES.get(str(slug or "").strip())
    if spec is None:
        raise MarketplaceFileError("Unknown marketplace product.")
    return spec


def product_path(slug: str) -> Path:
    spec = product_spec(slug)
    return storage_root() / str(spec["filename"])


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified_file_status(slug: str) -> dict:
    spec = product_spec(slug)
    try:
        path = product_path(slug)
    except MarketplaceFileError:
        return {
            "slug": slug,
            "filename": spec["filename"],
            "configured": False,
            "present": False,
            "verified": False,
            "access": spec["access"],
            "price_cents": spec["price_cents"],
        }
    if not path.is_file():
        return {
            "slug": slug,
            "filename": spec["filename"],
            "configured": True,
            "present": False,
            "verified": False,
            "access": spec["access"],
            "price_cents": spec["price_cents"],
        }
    data = path.read_bytes()
    digest = sha256_bytes(data)
    return {
        "slug": slug,
        "filename": spec["filename"],
        "configured": True,
        "present": True,
        "verified": digest == spec["sha256"] and len(data) == int(spec["bytes"]),
        "sha256": digest,
        "bytes": len(data),
        "expected_bytes": int(spec["bytes"]),
        "access": spec["access"],
        "price_cents": spec["price_cents"],
    }


def store_verified_pdf(slug: str, data: bytes) -> dict:
    spec = product_spec(slug)
    if not data:
        raise MarketplaceFileError("Uploaded file is empty.")
    if len(data) > MAX_PRODUCT_FILE_BYTES:
        raise MarketplaceFileError("Uploaded file exceeds the marketplace file limit.")
    if not data.startswith(b"%PDF"):
        raise MarketplaceFileError("Marketplace deliverable must be a PDF.")
    digest = sha256_bytes(data)
    if digest != spec["sha256"]:
        raise MarketplaceFileError("Uploaded PDF does not match the approved product fingerprint.")
    if len(data) != int(spec["bytes"]):
        raise MarketplaceFileError("Uploaded PDF size does not match the approved product.")
    path = product_path(slug)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return verified_file_status(slug)
