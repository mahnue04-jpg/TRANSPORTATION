"""Vendor-neutral connected-health and home-test constants. Coordination only."""
from __future__ import annotations

CONNECTED_HEALTH_DISCLAIMER = (
    "Lifesaver coordinates and stores user- or provider-supplied information. "
    "It is not a diagnostic medical device, does not perform laboratory testing, "
    "and does not diagnose, prescribe, or contact emergency services from a reading or result."
)
DEVICE_SIM_BANNER = "SIMULATION — NOT CONNECTED TO A REAL MEDICAL DEVICE"
KIT_COORDINATION_BANNER = (
    "Home-test coordination only. Lifesaver does not handle specimens, process labs, "
    "or generate diagnoses."
)
NO_DIAGNOSIS_BANNER = "No diagnosis is generated. Human review required for any flagged item."
NO_EMERGENCY_BANNER = "Emergency services contacted: no."

CONNECTED_DEVICE_TYPES = frozenset({
    "blood_pressure_monitor",
    "pulse_oximeter",
    "thermometer",
    "weight_scale",
    "glucose_meter",
    "cgm_bridge_placeholder",
    "heart_rate_device",
    "activity_mobility_device",
    "medication_dispenser_placeholder",
    "sleep_device_placeholder",
    "future_approved_health_sensor",
})
UNSUPPORTED_DEVICE_TYPES = frozenset({
    "unknown_unapproved_sensor",
})

CONNECTION_METHODS = frozenset({
    "simulated",
    "bluetooth_reserved",
    "wifi_reserved",
    "manual_entry",
})
INTEGRATION_STATUSES = frozenset({
    "NOT_CONNECTED",
    "DISCOVERED",
    "PAIRING",
    "CONNECTED",
    "DEGRADED",
    "OFFLINE",
    "REVOKED",
    "UNSUPPORTED",
    "SIMULATED",
})
APPROVAL_STATUSES = frozenset({
    "pending_simulated",
    "approved_simulated",
    "unsupported",
    "revoked",
})
DATA_QUALITY = frozenset({"unknown", "good", "degraded", "stale"})

HOME_TEST_CATEGORIES = frozenset({
    "urine_collection_placeholder",
    "oral_swab_placeholder",
    "saliva_collection_placeholder",
    "specimen_collection_placeholder",
    "future_approved_home_lab_kit",
})
KIT_STATUSES = (
    "ORDERED",
    "RECEIVED",
    "READY",
    "COLLECTED",
    "PACKAGED",
    "PICKUP_REQUESTED",
    "SHIPPED",
    "LAB_RECEIVED",
    "RESULT_PENDING",
    "RESULT_AVAILABLE",
    "PROVIDER_SHARED",
    "CANCELLED",
    "EXPIRED",
)
KIT_FORWARD = {
    "ORDERED": "RECEIVED",
    "RECEIVED": "READY",
    "READY": "COLLECTED",
    "COLLECTED": "PACKAGED",
    "PACKAGED": "PICKUP_REQUESTED",
    "PICKUP_REQUESTED": "SHIPPED",
    "SHIPPED": "LAB_RECEIVED",
    "LAB_RECEIVED": "RESULT_PENDING",
    "RESULT_PENDING": "RESULT_AVAILABLE",
    "RESULT_AVAILABLE": "PROVIDER_SHARED",
}
KIT_TERMINAL = frozenset({"CANCELLED", "EXPIRED", "PROVIDER_SHARED"})

RESULT_SOURCES = frozenset({
    "externally_supplied",
    "user_uploaded",
    "provider_lab_import_placeholder",
})
RESULT_REVIEW_STATUSES = frozenset({
    "RECEIVED",
    "NEEDS_HUMAN_REVIEW",
    "ACKNOWLEDGED",
    "PROVIDER_REVIEW_REQUESTED",
    "SHARED_CIRCLE",
    "CLOSED",
})
SHARE_STATUSES = frozenset({"none", "blocked", "queued_local", "shared_simulated", "revoked"})

CONSENT_CONNECTED_DEVICES = "connected_device_readings"
CONSENT_HOME_TESTS = "home_test_status"
CONSENT_RESULT_DOCS = "laboratory_result_documents"
CONSENT_PROVIDER_SHARE = "provider_sharing"
CONSENT_CIRCLE_HEALTH = "care_circle_health_share"

PHASE5_CONSENT_TYPES = (
    CONSENT_CONNECTED_DEVICES,
    CONSENT_HOME_TESTS,
    CONSENT_RESULT_DOCS,
    CONSENT_PROVIDER_SHARE,
    CONSENT_CIRCLE_HEALTH,
)
PHASE5_CONSENT_LABELS = {
    CONSENT_CONNECTED_DEVICES: "Store simulated connected-device readings (not from a real medical device)",
    CONSENT_HOME_TESTS: "Track home-test kit coordination status",
    CONSENT_RESULT_DOCS: "Store references to user- or provider-supplied result documents",
    CONSENT_PROVIDER_SHARE: "Allow simulated provider-share records (no real provider message)",
    CONSENT_CIRCLE_HEALTH: "Share connected-device and home-test status with my Care Circle",
}

PERM_VIEW_CONNECTED = "view_connected_devices"
PERM_VIEW_KITS = "view_home_tests"
PERM_VIEW_RESULTS = "view_result_documents"
PHASE5_PERMISSIONS = (PERM_VIEW_CONNECTED, PERM_VIEW_KITS, PERM_VIEW_RESULTS)
PHASE5_PERMISSION_LABELS = {
    PERM_VIEW_CONNECTED: "View simulated connected-health devices",
    PERM_VIEW_KITS: "View home-test kit status",
    PERM_VIEW_RESULTS: "View result-document references",
}

READING_KINDS = frozenset({
    "blood_pressure",
    "spo2",
    "temperature",
    "weight",
    "glucose",
    "heart_rate",
    "activity",
    "sleep_placeholder",
    "other_simulated",
})
