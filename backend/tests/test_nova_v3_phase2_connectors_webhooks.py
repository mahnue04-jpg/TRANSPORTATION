"""Synthetic connectors and lab-only webhooks."""
from __future__ import annotations

import pytest

from app.core.nova.v3.connectors import CONNECTOR_KINDS, STATES, SimulatedConnector
from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.kernel import NovaV3Kernel
from app.core.nova.v3.webhooks import ingest_webhook, sign_lab_payload


def test_all_connector_kinds_and_states() -> None:
    kernel = NovaV3Kernel()
    for kind in CONNECTOR_KINDS:
        for state in STATES:
            row = SimulatedConnector(
                connector_id=f"{kind}-{state}",
                kind=kind,
                organization_id="org-a",
                owner_user_id="owner-a",
                state=state,
            )
            if state == "CONNECTED":
                assert row.call()["live"] is False
            else:
                with pytest.raises(V3Error):
                    row.call()
    connected = kernel.register_connector(
        organization_id="org-a", owner_user_id="owner-a", kind="crm", state="CONNECTED"
    )
    assert kernel.call_connector(connected.connector_id, organization_id="org-a", owner_user_id="owner-a")["ok"] is True
    expired = kernel.register_connector(
        organization_id="org-a", owner_user_id="owner-a", kind="email", state="AUTH_EXPIRED"
    )
    with pytest.raises(V3Error) as required:
        kernel.call_connector(expired.connector_id, organization_id="org-a", owner_user_id="owner-a")
    assert required.value.code == "HUMAN_ACTION_REQUIRED"


def test_lab_webhook_signature_replay_and_stripe_forbidden() -> None:
    kernel = NovaV3Kernel()
    payload = {"type": "payment.updated", "amount": 10, "invoice_id": None}
    signature = sign_lab_payload(payload)
    first = kernel.ingest_lab_webhook(
        organization_id="org-a",
        owner_user_id="owner-a",
        provider="lab_processor",
        event_id="wh-1",
        payload=payload,
        signature=signature,
    )
    assert first.result == "ACCEPTED_SYNTHETIC"
    dup = kernel.ingest_lab_webhook(
        organization_id="org-a",
        owner_user_id="owner-a",
        provider="lab_processor",
        event_id="wh-1",
        payload=payload,
        signature=signature,
    )
    assert dup.duplicate is True
    assert dup.replayed is True
    with pytest.raises(V3Error) as bad:
        ingest_webhook(
            organization_id="org-a",
            owner_user_id="owner-a",
            provider="lab_processor",
            event_id="wh-2",
            payload=payload,
            signature="deadbeef",
        )
    assert bad.value.code == "INVALID_SIGNATURE"
    with pytest.raises(V3Error) as malformed:
        ingest_webhook(
            organization_id="org-a",
            owner_user_id="owner-a",
            provider="lab_processor",
            event_id="",
            payload="not-an-object",  # type: ignore[arg-type]
            signature=signature,
        )
    assert malformed.value.code == "MALFORMED_WEBHOOK"
    with pytest.raises(V3Error) as stripe:
        ingest_webhook(
            organization_id="org-a",
            owner_user_id="owner-a",
            provider="stripe",
            event_id="wh-s",
            payload=payload,
            signature=signature,
        )
    assert stripe.value.code == "STRIPE_FORBIDDEN"
