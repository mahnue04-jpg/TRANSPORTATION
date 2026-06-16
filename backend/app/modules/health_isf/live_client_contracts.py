"""Stable realtime contracts for driver app, provider app, and dispatcher console."""

from __future__ import annotations

from datetime import datetime


def build_live_client_contracts(organization_id: str) -> dict:
    websocket_payload_contract = {
        "type": "event|event_batch|ping|pong|auth_refresh",
        "event_type": "string",
        "payload": "object",
        "timestamp": "iso8601",
        "organization_id": organization_id,
        "contract_version": "v1.operational-intelligence",
    }

    return {
        "organization_id": organization_id,
        "driver_app": {
            "role_scope": ["driver"],
            "visibility": ["assigned rides", "own position", "status updates", "personal alerts"],
            "hydration_safe": True,
            "realtime_safe": True,
            "websocket_payload_contract": websocket_payload_contract,
        },
        "provider_app": {
            "role_scope": ["provider"],
            "visibility": ["provider zones", "provider ride queue", "provider SLA alerts"],
            "hydration_safe": True,
            "realtime_safe": True,
            "websocket_payload_contract": websocket_payload_contract,
        },
        "dispatcher_console": {
            "role_scope": ["dispatcher", "admin", "super_admin_support"],
            "visibility": ["global operational map", "dispatch recommendations", "incident clusters", "governed approvals"],
            "hydration_safe": True,
            "realtime_safe": True,
            "websocket_payload_contract": websocket_payload_contract,
        },
        "shared_operational_contracts": {
            "stable_websocket_payloads": True,
            "role_scoped_visibility": True,
            "tenant_isolated": True,
            "approval_governed_actions": True,
            "no_unrestricted_autonomy": True,
        },
        "generated_at": datetime.utcnow().isoformat(),
    }
