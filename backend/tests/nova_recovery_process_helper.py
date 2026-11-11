"""CI-only subprocess for real process-boundary recovery.

Uses disposable PostgreSQL and a temporary on-disk fake object store.
Never run against a customer database or real S3 bucket.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.nova.work_revenue import operations_recoverable_csv as recovery


class SharedFakePrivateStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        ref = secrets.token_hex(20) + ".bin"
        data = stream.read()
        (self.directory / ref).write_bytes(data)
        return "synthetic-private", ref, len(data)

    def retrieve(self, *, storage_ref):
        if not storage_ref.endswith(".bin") or "/" in storage_ref or "\\" in storage_ref:
            raise ValueError("Invalid synthetic storage reference")
        return (self.directory / storage_ref).read_bytes(), "application/octet-stream"

    def delete(self, *, storage_ref):
        if not storage_ref.endswith(".bin") or "/" in storage_ref or "\\" in storage_ref:
            raise ValueError("Invalid synthetic storage reference")
        (self.directory / storage_ref).unlink(missing_ok=True)


def main():
    # Test helper cannot quietly use an environment's default DB.
    url = os.environ["NOVA_CSV_CI_DATABASE_URL"]
    if ("127.0.0.1" not in url or not url.startswith("postgresql")
            or os.getenv("NOVA_CSV_PROCESS_TEST", "") != "synthetic-only"):
        raise RuntimeError("CI-only disposable loopback PostgreSQL required")
    store_dir = os.environ["NOVA_CSV_CI_FAKE_STORE"]
    recovery._store = lambda: SharedFakePrivateStore(store_dir)
    job_id, step, clock = sys.argv[1:4]
    timestamp = datetime.fromisoformat(clock)
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            if step == "claim-and-exit":
                claimed = recovery.claim(
                    db, org="org-a", owner="owner-a", job_id=job_id,
                    now=timestamp, lease_seconds=60,
                )
                print(json.dumps({"token": claimed["token"], "attempts": claimed["attempts"]}))
            elif step == "resume":
                result = recovery.process_job(
                    db, org="org-a", owner="owner-a", job_id=job_id,
                    authorization_check=lambda engagement, task: None,
                    now=timestamp,
                )
                print(json.dumps(result))
            else:
                raise ValueError("Unsupported synthetic recovery test step")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
