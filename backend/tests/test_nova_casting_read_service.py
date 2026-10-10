"""Standalone checks for inactive organizer application read composition."""
import importlib.util
import sys
import types
from pathlib import Path
import pytest

FOLDER = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"

def load():
    prefix = "_casting_read_service_test"
    pkg = types.ModuleType(prefix)
    pkg.__path__ = [str(FOLDER)]
    sys.modules[prefix] = pkg
    for name in ("casting_policy", "casting_identity", "casting_membership", "casting_workflow_policy",
                 "casting_responses", "casting_access", "casting_read_service"):
        spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", FOLDER / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{prefix}.casting_read_service"], sys.modules[f"{prefix}.casting_access"]


def test_verified_organizer_can_read_but_other_tenant_cannot():
    service, access = load()
    membership = dict(user_id="reviewer", organization_id="org1", nova_tenant_id="tenant1",
                      active=True, organization_verified=True, casting_role="reviewer")
    app = dict(id="app1", owner_id="org1", applicant_id="applicant", campaign_id="camp1",
               status="SUBMITTED", created_at="today", storage_key="hidden")
    campaign = dict(id="camp1", owner_id="org1")
    params = dict(session_user_id="reviewer", session_tenant_id="tenant1",
                  casting_organization_id="org1", application_id="app1",
                  membership_lookup=lambda user, org: membership,
                  application_lookup=lambda application_id: app,
                  campaign_lookup=lambda campaign_id: campaign)
    assert "storage_key" not in service.read_organizer_application(**params)
    with pytest.raises(access.CastingAccessDenied):
        service.read_organizer_application(**{**params, "session_tenant_id": "tenant2"})
    with pytest.raises(access.CastingAccessDenied):
        service.read_organizer_application(**{**params, "application_lookup": lambda _: {**app, "owner_id": "org2"}})
    with pytest.raises(access.CastingAccessDenied):
        service.read_organizer_application(**{**params, "membership_lookup": lambda u, o: None})
