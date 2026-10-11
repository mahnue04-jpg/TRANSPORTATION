"""Standalone privacy rules for casting audit events."""
import importlib.util
from pathlib import Path
import pytest

PATH = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio/casting_audit.py"

def module():
    spec = importlib.util.spec_from_file_location("casting_audit_test", PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def test_casting_audit_allowlist_and_minimal_fields():
    m = module()
    event = m.casting_audit_event(actor_id="u1", organization_id="org1",
                                  action="review.updated", object_id="application1")
    assert set(event) == {"actor_id", "organization_id", "action", "object_id", "occurred_at"}
    assert event["action"] == "review.updated"
    with pytest.raises(ValueError):
        m.casting_audit_event(actor_id="u1", organization_id="org1", action="video.exported", object_id="application1")
    with pytest.raises(ValueError):
        m.casting_audit_event(actor_id="", organization_id="org1", action="review.updated", object_id="application1")
