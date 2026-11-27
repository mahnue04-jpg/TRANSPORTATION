"""Private artifact manifest contract: synthetic bytes only, offline."""
from dataclasses import replace
from uuid import uuid4

import pytest

from app.core.nova.work_revenue.operations_artifact_manifest import (
    authorize_artifact_download, build_artifact_manifest,
)
from app.core.nova.work_revenue.operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope,
)


def _sample():
    owner = str(uuid4())
    job = TenantJobScope(tenant_id=owner, job_id=str(uuid4()))
    content = b"account,total\nA,12\n"
    manifest = build_artifact_manifest(
        acting_tenant_id=owner, job=job, artifact_id=str(uuid4()),
        content=content,
    )
    return owner, manifest, content


def test_download_requires_explicit_human_approval():
    owner, manifest, content = _sample()
    with pytest.raises(TenantAccessDenied):
        authorize_artifact_download(
            acting_tenant_id=owner, manifest=manifest, content=content
        )
    assert authorize_artifact_download(
        acting_tenant_id=owner,
        manifest=replace(manifest, approved_for_download=True),
        content=content,
    ) == content


def test_cross_tenant_download_is_denied_even_when_approved():
    _, manifest, content = _sample()
    with pytest.raises(TenantAccessDenied):
        authorize_artifact_download(
            acting_tenant_id=str(uuid4()),
            manifest=replace(manifest, approved_for_download=True),
            content=content,
        )


@pytest.mark.parametrize("change", [
    lambda m: replace(m, storage_key="operations-csv/other"),
    lambda m: replace(m, byte_count=m.byte_count + 1),
    lambda m: replace(m, sha256_hex="0" * 64),
])
def test_corrupt_or_tampered_manifest_denied(change):
    owner, manifest, content = _sample()
    with pytest.raises(TenantAccessDenied):
        authorize_artifact_download(
            acting_tenant_id=owner,
            manifest=change(replace(manifest, approved_for_download=True)),
            content=content,
        )


def test_content_integrity_checks_same_size_mutation():
    owner, manifest, content = _sample()
    changed = content.replace(b"12", b"99")
    assert len(changed) == len(content)
    with pytest.raises(TenantAccessDenied):
        authorize_artifact_download(
            acting_tenant_id=owner,
            manifest=replace(manifest, approved_for_download=True),
            content=changed,
        )


def test_untrusted_metadata_denied():
    owner, _, content = _sample()
    with pytest.raises(TenantAccessDenied):
        authorize_artifact_download(
            acting_tenant_id=owner, manifest=None, content=content
        )


def test_empty_artifact_refused():
    owner = str(uuid4())
    with pytest.raises(ValueError):
        build_artifact_manifest(
            acting_tenant_id=owner,
            job=TenantJobScope(tenant_id=owner, job_id=str(uuid4())),
            artifact_id=str(uuid4()), content=b"",
        )
