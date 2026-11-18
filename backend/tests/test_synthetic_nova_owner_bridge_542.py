"""Strict synthetic Workspace session/organization authorization tests."""
import pytest

from synthetic_nova_replay_542 import SyntheticReplayLedger
from synthetic_nova_owner_bridge_542 import (
    ServerAuthenticatedPrincipal, owner_journey_view,
)


def _principal(org="org-A", role="admin", grants=frozenset({"admin"}), uid="owner-1"):
    return ServerAuthenticatedPrincipal(
        user_id=uid, organization_id=org,
        active_role=role, authorized_roles=grants,
    )


def _ledger(tmp_path):
    ledger = SyntheticReplayLedger(tmp_path / "synthetic-owner.sqlite")
    ledger.accept(
        organization_id="org-A", correlation_id="journey-1",
        event_id="evt-0", idempotency_key="key-0",
        fingerprint="synthetic-lead", step=0,
    )
    ledger.accept(
        organization_id="org-A", correlation_id="journey-1",
        event_id="evt-1", idempotency_key="key-1",
        fingerprint="synthetic-review", step=1,
    )
    return ledger


def _read(ledger, resolver, token="opaque-test-session"):
    return owner_journey_view(
        opaque_session=token, verify_session=resolver,
        ledger=ledger, correlation_id="journey-1",
    )


def test_authorized_owner_sees_pending_synthetic_journey(tmp_path):
    ledger = _ledger(tmp_path)
    result = _read(ledger, lambda token: _principal())
    assert result.status == "pending_approval"
    assert result.pending_owner_approval is True
    assert result.assigned_agent == "owner"
    ledger.close()


@pytest.mark.parametrize("role,grants", [
    ("staff", frozenset({"staff"})),
    ("staff", frozenset({"staff", "admin"})),
    ("super_admin_support", frozenset({"super_admin_support", "admin"})),
    ("analytics_readonly", frozenset({"analytics_readonly"})),
    ("admin", frozenset({"staff"})),
])
def test_role_or_grant_mismatch_denied(tmp_path, role, grants):
    ledger = _ledger(tmp_path)
    with pytest.raises(PermissionError, match="owner role"):
        _read(ledger, lambda token: _principal(role=role, grants=grants))
    ledger.close()


@pytest.mark.parametrize("org", ["org-B", "global", "", None])
def test_wrong_or_missing_org_never_returns_other_org_journey(tmp_path, org):
    ledger = _ledger(tmp_path)
    if org == "org-B":
        result = _read(ledger, lambda token: _principal(org=org))
        assert result.status == "not_found"
    else:
        with pytest.raises(PermissionError):
            _read(ledger, lambda token: _principal(org=org))
    ledger.close()


def test_missing_session_denied_before_verifier_call(tmp_path):
    ledger = _ledger(tmp_path)
    invoked = []
    with pytest.raises(PermissionError):
        _read(ledger, lambda token: invoked.append(token), token="")
    assert invoked == []
    ledger.close()


def test_invalid_verifier_result_denied(tmp_path):
    ledger = _ledger(tmp_path)
    with pytest.raises(PermissionError, match="authenticated principal"):
        _read(ledger, lambda token: {"organization_id": "org-A", "role": "admin"})
    ledger.close()


def test_missing_user_identity_denied(tmp_path):
    ledger = _ledger(tmp_path)
    with pytest.raises(PermissionError, match="identity required"):
        _read(ledger, lambda token: _principal(uid=""))
    ledger.close()


def test_view_is_derived_from_verified_org_not_request_org(tmp_path):
    ledger = _ledger(tmp_path)
    observed = []
    def verifier(token):
        observed.append(token)
        return _principal(org="org-B")
    result = _read(ledger, verifier)
    assert observed == ["opaque-test-session"]
    assert result.status == "not_found"
    ledger.close()
