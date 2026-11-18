"""Offline contract acceptance for Studio -> Growth. No app package imports."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types

import pytest

CORE = Path(__file__).resolve().parents[1] / "app/core/nova"
PACKAGE = "_test_only_nova_studio_contract"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(CORE)]
sys.modules[PACKAGE] = pkg


def load(name, filename):
    spec = importlib.util.spec_from_file_location(PACKAGE + "." + name, CORE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


events = load("agent_events", "agent_events.py")
adapter = load("studio_growth_adapter", "studio_growth_adapter.py")
NOW = datetime(2026, 11, 17, 20, 0, tzinfo=timezone.utc)


def metadata():
    return dict(organization_id="org-A", campaign_id="campaign-1",
                asset_id="asset-1", project_id="project-1",
                status="completed", asset_kind="video",
                review_state="owner_approved")


def convert(raw=None, enabled=True, **kwargs):
    return adapter.staging_asset_event(
        metadata() if raw is None else raw,
        organization_id=kwargs.pop("organization_id", "org-A"),
        source_identity=kwargs.pop("source_identity", "studio-service-A"),
        occurred_at=NOW, enabled=enabled,
    )


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOVA_STUDIO_GROWTH_STAGING_ADAPTER_ENABLED", raising=False)
    with pytest.raises(PermissionError):
        convert(enabled=None)


def test_completed_owner_approved_asset_maps_to_synthetic_event(monkeypatch):
    monkeypatch.delenv("NOVA_STUDIO_GROWTH_LIVE_ENABLED", raising=False)
    evt = convert()
    assert evt.synthetic is True
    assert evt.event_type == events.EventType.ASSET_READY
    assert (evt.source_agent, evt.target_agent) == (
        events.Agent.CREATIVE_STUDIO, events.Agent.GROWTH
    )
    assert evt.payload_reference == "synthetic:asset-1"
    assert evt.correlation_id == "campaign-1"
    assert evt.organization_id == "org-A"
    assert not any(key in evt.to_mapping() for key in ("url", "email", "media_bytes"))
    assert "app.main" not in sys.modules


@pytest.mark.parametrize("key,value", [
    ("customer_email", "private@example.invalid"),
    ("download_url", "https://example.invalid/video.mp4"),
    ("api_key", "secret"),
    ("media_bytes", b"fake"),
    ("script", "private script"),
])
def test_reject_extra_sensitive_and_media_fields(key, value):
    row = metadata()
    row[key] = value
    with pytest.raises(ValueError):
        convert(row)


@pytest.mark.parametrize("key,value", [
    ("status", "pending"),
    ("review_state", "not_reviewed"),
    ("asset_kind", "audio"),
])
def test_reject_unapproved_or_unsupported_assets(key, value):
    row = metadata()
    row[key] = value
    with pytest.raises((ValueError, PermissionError)):
        convert(row)


def test_wrong_tenant_and_identity_fail_closed():
    with pytest.raises(PermissionError):
        convert(organization_id="org-B")
    with pytest.raises(PermissionError):
        convert(source_identity="not authorized to act")


def test_no_live_adapter_even_if_synthetic_enabled(monkeypatch):
    monkeypatch.setenv("NOVA_STUDIO_GROWTH_LIVE_ENABLED", "true")
    with pytest.raises(PermissionError):
        convert()


def test_duplicate_input_is_deterministic():
    assert convert() == convert()


def test_missing_required_field_is_rejected():
    row = metadata()
    del row["project_id"]
    with pytest.raises(ValueError):
        convert(row)


def studio_rows():
    from types import SimpleNamespace
    project = SimpleNamespace(id="project-1", owner_id="owner-1")
    asset = SimpleNamespace(id="asset-1", project_id="project-1",
                            owner_id="owner-1", kind="video", status="GENERATED")
    approval = dict(organization_id="org-A", project_id="project-1",
                    asset_id="asset-1", owner_id="owner-1", approved=True,
                    action="share_campaign_asset_with_growth")
    return project, asset, approval


def from_rows(project=None, asset=None, approval=None):
    p, a, evidence = studio_rows()
    return adapter.staged_studio_record_event(
        project=p if project is None else project,
        asset=a if asset is None else asset,
        owner_approval=evidence if approval is None else approval,
        campaign_id="campaign-1", organization_id="org-A",
        authenticated_owner_id="owner-1",
        authenticated_studio_principal="studio-service-A",
        occurred_at=NOW, enabled=True,
    )


def test_actual_studio_record_status_projects_only_opaque_metadata():
    evt = from_rows()
    assert evt.event_type == events.EventType.ASSET_READY
    assert evt.payload_reference == "synthetic:asset-1"
    assert evt.synthetic is True


@pytest.mark.parametrize("field,value", [
    ("owner_id", "attacker"),
    ("project_id", "another-project"),
    ("status", "PLANNING_ONLY"),
    ("kind", "script"),
])
def test_forged_studio_asset_rows_are_denied(field, value):
    from types import SimpleNamespace
    p, a, evidence = studio_rows()
    altered = SimpleNamespace(**{**vars(a), field: value})
    with pytest.raises(PermissionError):
        from_rows(project=p, asset=altered, approval=evidence)


@pytest.mark.parametrize("field,value", [
    ("organization_id", "org-B"),
    ("project_id", "other-project"),
    ("asset_id", "other-asset"),
    ("owner_id", "wrong-owner"),
    ("approved", False),
    ("action", "post_to_social_media"),
])
def test_owner_review_must_exactly_match_asset(field, value):
    p, a, approval = studio_rows()
    approval[field] = value
    with pytest.raises(PermissionError):
        from_rows(project=p, asset=a, approval=approval)


def test_unknown_approval_fields_cannot_authorize():
    p, a, approval = studio_rows()
    approval["customer_email"] = "private@example.invalid"
    with pytest.raises(PermissionError):
        from_rows(project=p, asset=a, approval=approval)


def test_owner_scoped_store_and_persisted_approval_reader_required():
    project, asset, approval = studio_rows()

    class ReadOnlyStore:
        def __init__(self):
            self.calls = []
        def get_project(self, project_id, owner_id):
            self.calls.append(("project", project_id, owner_id))
            return project if (project_id, owner_id) == ("project-1", "owner-1") else None
        def list_assets(self, project_id, owner_id):
            self.calls.append(("assets", project_id, owner_id))
            return [asset] if (project_id, owner_id) == ("project-1", "owner-1") else []

    calls = []
    def approval_reader(**kwargs):
        calls.append(kwargs)
        return approval

    store = ReadOnlyStore()
    event = adapter.read_studio_asset_for_growth(
        studio_store=store, approval_reader=approval_reader,
        project_id="project-1", asset_id="asset-1",
        campaign_id="campaign-1", organization_id="org-A",
        authenticated_owner_id="owner-1",
        authenticated_studio_principal="studio-service-A",
        occurred_at=NOW, enabled=True,
    )
    assert event.synthetic and event.payload_reference == "synthetic:asset-1"
    assert store.calls == [
        ("project", "project-1", "owner-1"),
        ("assets", "project-1", "owner-1"),
    ]
    assert calls == [dict(
        organization_id="org-A", owner_id="owner-1", project_id="project-1",
        asset_id="asset-1", action="share_campaign_asset_with_growth",
    )]


@pytest.mark.parametrize("failure", [
    "disabled", "missing_project", "missing_asset", "missing_approval",
    "denied_approval", "duplicate_asset", "wrong_owner",
])
def test_server_side_source_of_truth_boundary_fails_closed(failure):
    project, asset, approval = studio_rows()
    from types import SimpleNamespace

    class Store:
        def get_project(self, project_id, owner_id):
            if failure == "missing_project":
                return None
            return project
        def list_assets(self, project_id, owner_id):
            if failure == "missing_asset":
                return []
            if failure == "duplicate_asset":
                return [asset, asset]
            if failure == "wrong_owner":
                return [SimpleNamespace(**{**vars(asset), "owner_id": "other"})]
            return [asset]

    def reader(**kwargs):
        if failure == "missing_approval":
            return None
        if failure == "denied_approval":
            return {**approval, "approved": False}
        return approval

    with pytest.raises(PermissionError):
        adapter.read_studio_asset_for_growth(
            studio_store=Store(), approval_reader=reader,
            project_id="project-1", asset_id="asset-1",
            campaign_id="campaign-1", organization_id="org-A",
            authenticated_owner_id="owner-1",
            authenticated_studio_principal="studio-service-A",
            occurred_at=NOW, enabled=failure != "disabled",
        )


def test_untrusted_approval_dictionary_cannot_be_used_as_reader():
    project, asset, approval = studio_rows()
    from types import SimpleNamespace
    store = SimpleNamespace(
        get_project=lambda *args: project,
        list_assets=lambda *args: [asset],
    )
    with pytest.raises(PermissionError):
        adapter.read_studio_asset_for_growth(
            studio_store=store, approval_reader=approval,
            project_id="project-1", asset_id="asset-1",
            campaign_id="campaign-1", organization_id="org-A",
            authenticated_owner_id="owner-1",
            authenticated_studio_principal="studio-service-A",
            occurred_at=NOW, enabled=True,
        )
