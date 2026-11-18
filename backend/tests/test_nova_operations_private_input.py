"""Synthetic no-network private input contract tests."""
import hashlib
import pytest

from app.core.nova.work_revenue.operations_private_input import (
    PrivateInputBlocked, persist_private_csv_input, load_private_csv_input,
)


class FakePrivateStore:
    def __init__(self):
        self.items = {}
        self.put_count = 0

    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        assert category.startswith("nova-csv-input-")
        self.put_count += 1
        key = f"{organization_id}/{application_id}/{category}/{filename}"
        raw = stream.read()
        self.items[key] = (raw, content_type)
        return "private-fake", key, len(raw)

    def retrieve(self, *, storage_ref):
        return self.items[storage_ref]


def _save(store, raw=b"Name\nAda\n"):
    return persist_private_csv_input(
        organization_id="synthetic-org", owner_user_id="owner-1",
        job_id="synthetic-job", raw=raw, store=store)


def _load(store, receipt):
    return load_private_csv_input(
        organization_id="synthetic-org", owner_user_id="owner-1",
        job_id="synthetic-job", storage_ref=receipt.storage_ref,
        expected_sha256=receipt.sha256, store=store)


def test_private_input_write_read_and_hash():
    store = FakePrivateStore()
    raw = b"Name\nAda\n"
    receipt = _save(store, raw)
    assert receipt.sha256 == hashlib.sha256(raw).hexdigest()
    assert receipt.size == len(raw)
    assert _load(store, receipt) == raw
    assert store.put_count == 1


def test_private_input_rejects_corrupted_and_missing_objects():
    store = FakePrivateStore()
    receipt = _save(store)
    store.items[receipt.storage_ref] = (b"Name\nMallory\n", "text/csv")
    with pytest.raises(PrivateInputBlocked, match="fingerprint mismatch"):
        _load(store, receipt)
    del store.items[receipt.storage_ref]
    with pytest.raises(PrivateInputBlocked, match="cannot be retrieved"):
        _load(store, receipt)


def test_private_input_scope_and_size_validation():
    store = FakePrivateStore()
    with pytest.raises(PrivateInputBlocked, match="scope"):
        persist_private_csv_input(
            organization_id="../invalid", owner_user_id="owner-1",
            job_id="synthetic-job", raw=b"a", store=store)
    with pytest.raises(PrivateInputBlocked, match="size"):
        _save(store, b"")
    with pytest.raises(PrivateInputBlocked, match="size"):
        _save(store, b"x" * 1_000_001)
    assert store.put_count == 0


def test_private_input_ref_and_sha_required():
    store = FakePrivateStore()
    receipt = _save(store)
    with pytest.raises(PrivateInputBlocked, match="reference required"):
        load_private_csv_input(
            organization_id="synthetic-org", owner_user_id="owner-1",
            job_id="synthetic-job", storage_ref="", expected_sha256=receipt.sha256,
            store=store)
    with pytest.raises(PrivateInputBlocked, match="fingerprint"):
        load_private_csv_input(
            organization_id="synthetic-org", owner_user_id="owner-1",
            job_id="synthetic-job", storage_ref=receipt.storage_ref,
            expected_sha256="invalid", store=store)


def test_bad_store_receipt_never_claims_success():
    class TruncatedStore(FakePrivateStore):
        def store(self, **kwargs):
            bucket, key, size = super().store(**kwargs)
            return bucket, key, size - 1
    with pytest.raises(PrivateInputBlocked, match="not confirmed"):
        _save(TruncatedStore())


def test_private_input_rejects_cross_tenant_reference_before_object_read():
    store = FakePrivateStore()
    receipt = _save(store)
    attempted = []
    actual_retrieve = store.retrieve
    def guarded_retrieve(*, storage_ref):
        attempted.append(storage_ref)
        return actual_retrieve(storage_ref=storage_ref)
    store.retrieve = guarded_retrieve
    with pytest.raises(PrivateInputBlocked, match="scope mismatch"):
        load_private_csv_input(
            organization_id="another-org", owner_user_id="owner-1",
            job_id="synthetic-job", storage_ref=receipt.storage_ref,
            expected_sha256=receipt.sha256, store=store)
    assert attempted == []


def test_private_input_rejects_unscoped_storage_receipt():
    class BadRefStore(FakePrivateStore):
        def store(self, **kwargs):
            bucket, _key, size = super().store(**kwargs)
            return bucket, "other-org/other-job/unscoped.csv", size
    with pytest.raises(PrivateInputBlocked, match="not confirmed"):
        _save(BadRefStore())
