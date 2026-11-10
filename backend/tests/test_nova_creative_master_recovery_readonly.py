"""Safe, read-only recovery status tests. No customer files or provider calls."""
import json
from types import SimpleNamespace

from app.core.nova.creative_studio import calendar as studio
from app.core.nova.creative_studio import private_object_storage as remote


def _case(monkeypatch, *, claim_state="ERROR", asset_version=None,
          exists=True, claim_job="job-1", job_status="ERROR"):
    version = "a" * 64
    sha = "b" * 64
    asset = SimpleNamespace(
        id="master-new", kind="video", url="private-studio-s3://owner/project/master.mp4",
        created_at="2026-11-09T00:02:00+00:00",
        metadata={"pipeline": "calendar_chapter_master",
                  "calendar_entry_id": "entry",
                  "pinned_version_sha256": asset_version or version,
                  "sha256": sha},
    )
    job = SimpleNamespace(
        id="job-1", kind="calendar_master:entry", status=job_status,
        created_at="2026-11-09T00:01:00+00:00", result_asset_ids=[],
        as_dict=lambda: {"id": "job-1", "status": job.status},
    )
    claim = SimpleNamespace(
        job_id=claim_job, state=claim_state,
        updated_at="2026-11-09T00:01:00+00:00",
        checkpoint_json=json.dumps({"pinned_master": {"version_sha256": version}}),
    )
    calls = {"save_job": 0, "commit": 0}
    class Store:
        def list_jobs(self, project_id, owner_id):
            return [job]
        def list_assets(self, project_id, owner_id):
            return [asset]
        def save_job(self, value):
            calls["save_job"] += 1
            raise AssertionError("GET master status must never persist a job")
    class DB:
        def get(self, *args):
            return claim
        def commit(self):
            calls["commit"] += 1
            raise AssertionError("GET master status must never commit a claim")
    monkeypatch.setattr(studio, "DbCreativeStudioStore", lambda db: Store())
    monkeypatch.setattr(remote, "enabled", lambda: True)
    monkeypatch.setattr(remote, "object_exists", lambda *args: exists)
    studio._master_export_active.discard(("owner", "project", "entry"))
    return DB(), claim, job, calls


def test_valid_saved_master_is_recoverable_but_get_cannot_finalize(monkeypatch):
    db, claim, job, calls = _case(monkeypatch)
    result = studio._master_job_status(db, "owner", "project", "entry")
    assert result["status"] == "RECOVERABLE_ASSET_FOUND"
    assert result["candidate_asset_id"] == "master-new"
    assert result["job"]["status"] == "ERROR"
    assert claim.state == "ERROR"
    assert job.status == "ERROR"
    assert calls == {"save_job": 0, "commit": 0}


def test_stale_running_worker_is_not_overwritten_by_read_only_status(monkeypatch):
    db, claim, job, calls = _case(monkeypatch, claim_state="RUNNING", job_status="RUNNING")
    result = studio._master_job_status(db, "owner", "project", "entry")
    assert result["status"] == "RECOVERABLE_ASSET_FOUND"
    assert claim.state == "RUNNING"
    assert job.status == "RUNNING"
    assert calls == {"save_job": 0, "commit": 0}


def test_recovery_rejects_mismatched_media_or_missing_remote_bytes(monkeypatch):
    for changes in ({"asset_version": "f" * 64}, {"exists": False},
                    {"claim_job": "unrelated-job"}):
        db, claim, job, calls = _case(monkeypatch, **changes)
        result = studio._master_job_status(db, "owner", "project", "entry")
        assert result["status"] != "GENERATED"
        assert result["status"] != "RECOVERABLE_ASSET_FOUND" or changes == {}
        assert calls == {"save_job": 0, "commit": 0}
