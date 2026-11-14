"""Read-only inspector for an exported Growth Agent PostgreSQL backup archive.

Run locally on a copy of the downloaded archive. Does not extract, restore,
connect to PostgreSQL, print credentials, or modify the input file.
This checks archive structure and checksum, NOT successful PostgreSQL recovery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path


def inspect_archive(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError("Backup archive does not exist")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
    with tarfile.open(path, mode="r:*") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("Backup archive is empty")
        regular_files = []
        for member in members:
            name = member.name
            normalized = name.replace("\\", "/")
            parts = normalized.split("/")
            if (name.startswith("/") or name.startswith("\\") or ".." in parts
                    or member.issym() or member.islnk() or member.isdev()):
                raise ValueError("Unsafe archive entry")
            if member.isfile():
                regular_files.append((normalized, member.size))
        if not regular_files:
            raise ValueError("Archive contains no files")
        # pg_dump -Fd contains toc.dat and numbered data blobs; wrapped tarballs
        # commonly carry a root folder. A .tar extension alone proves nothing.
        toc_present = any(name.split("/")[-1] == "toc.dat" for name, _ in regular_files)
        if toc_present:
            format_guess = "directory-format PostgreSQL dump wrapped in tar"
        else:
            format_guess = "tar archive; PostgreSQL restore format unverified"
    return {
        "archive_bytes": path.stat().st_size,
        "sha256": sha.hexdigest(),
        "member_count": len(members),
        "regular_file_count": len(regular_files),
        "toc_dat_present": toc_present,
        "archive_classification": format_guess,
        "structural_inspection_only": True,
        "postgres_restore_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Path to a local export .tar/.tar.gz")
    args = parser.parse_args()
    try:
        report = inspect_archive(args.archive)
    except (OSError, tarfile.TarError, ValueError):
        print("Archive inspection failed; do not attempt staging deployment")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
