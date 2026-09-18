"""Product constants, consent keys, and non-clinical disclaimers."""
from __future__ import annotations

from app.modules.lifesaver.connected_health.constants import (
    PHASE5_CONSENT_LABELS,
    PHASE5_CONSENT_TYPES,
    PHASE5_PERMISSION_LABELS,
    PHASE5_PERMISSIONS,
)

PRODUCT_NAME = "Healthcare Technology Lifesaver AI Care Cloud"
PRODUCT_VERSION = "v2"
CONSENT_VERSION = "lifesaver-v2"

PRODUCT_DISCLAIMER = (
    "Lifesaver AI Care Cloud is software for care coordination, accessibility, "
    "reminders, and wellness support. It is not a diagnostic medical device and "
    "does not diagnose, treat, monitor, or detect medical emergencies."
)

SOS_DISCLAIMER = (
    "This SOS flow is a demonstration only. It does not contact 911, emergency "
    "services, clinicians, or guarantee any response. If you have an emergency, "
    "use local emergency services directly."
)

AI_DISCLAIMER = (
    "Lifesaver AI can help you organize care tasks and find features. It cannot "
    "diagnose conditions, recommend treatment, or replace a clinician."
)

READING_SOURCE_DISCLAIMER = (
    "Readings are user-entered or simulated. They are not claimed to come from "
    "a medical device unless an approved integration later supplies them."
)

PROFILE_ROLES = frozenset({"member", "caregiver", "coordinator"})
DEFAULT_PROFILE_ROLE = "member"

CONSENT_TYPES = (
    "care_cloud_use",
    "caregiver_sharing",
    "health_readings",
    "reminders",
    "wellness_checkins",
    "journal",
    "transport_status",
    "ai_conversation",
    "sos_demonstration",
    "audit_retention",
    "caregiver_notifications",
    "simulated_device_ingest",
    "hardware_simulation",
    "video_session_simulation",
) + PHASE5_CONSENT_TYPES

CONSENT_LABELS = {
    "care_cloud_use": "Use Lifesaver Care Cloud",
    "caregiver_sharing": "Share selected information with my Care Circle",
    "health_readings": "Store user-entered or simulated health readings",
    "reminders": "Create and store reminders",
    "wellness_checkins": "Store wellness check-ins",
    "journal": "Store my health journal entries",
    "transport_status": "Show transportation connection status",
    "ai_conversation": "Use the AI Care conversation interface",
    "sos_demonstration": "Use the SOS demonstration workflow",
    "audit_retention": "Keep an audit trail of permission and access events",
    "caregiver_notifications": "Queue local caregiver notification simulations",
    "simulated_device_ingest": "Enter simulated-device readings (not from a medical device)",
    "hardware_simulation": "Use simulated Home Hub and Car Hub controls (no real devices)",
    "video_session_simulation": "Request a local simulated video session (no live video provider)",
    **PHASE5_CONSENT_LABELS,
}

READING_TYPES = frozenset({
    "blood_pressure",
    "glucose",
    "oxygen_saturation",
    "spo2",
    "temperature",
    "weight",
})

READING_UNITS = {
    "blood_pressure": "mmHg",
    "glucose": "mg/dL",
    "oxygen_saturation": "%",
    "spo2": "%",
    "temperature": "F",
    "weight": "lb",
}

READING_SOURCES = frozenset({
    "user_entered",
    "simulated",
    "simulated_device",
    "external_device_reserved",
})
SOURCE_USER_ENTERED = "user_entered"
SOURCE_SIMULATED = "simulated"
SOURCE_SIMULATED_DEVICE = "simulated_device"
SOURCE_EXTERNAL_RESERVED = "external_device_reserved"

TRANSPORT_REQUEST_STATUSES = frozenset({
    "requested",
    "needs_review",
    "ready_for_handoff",
    "handed_off_simulated",
    "cancelled",
})
NOTIFICATION_STATUSES = frozenset({
    "draft",
    "queued_local",
    "suppressed",
    "delivered_simulated",
    "failed_simulated",
})
NOTIFICATION_CHANNELS = frozenset({"email", "sms"})
NOTIFICATION_TYPES = frozenset({
    "appointment_reminder",
    "medication_reminder",
    "transport_update",
    "care_circle_invite",
    "handoff_assigned",
    "task_assigned",
    "alert_ack_request",
    "safety_event_review",
})
TRANSPORT_COORD_DISCLAIMER = (
    "Transportation coordination only. This does not dispatch a ride."
)
NOTIFICATION_SIM_LABEL = "LOCAL SIMULATION — no external message sent."
DEVICE_SIM_LABEL = "SIMULATED — NOT FROM A MEDICAL DEVICE"

CAREGIVER_PERMISSIONS = (
    "view_today",
    "view_medications",
    "view_appointments",
    "view_wellness",
    "view_journal",
    "view_readings",
    "view_transport",
    "receive_alerts",
    "acknowledge_alerts",
    "manage_tasks",
    "handoff",
    "view_devices",
) + PHASE5_PERMISSIONS

DEFAULT_CAREGIVER_PERMISSIONS = (
    "view_today",
    "receive_alerts",
    "acknowledge_alerts",
)

CAREGIVER_PERMISSION_LABELS = {
    "view_today": "View Today",
    "view_medications": "View medications",
    "view_appointments": "View appointments",
    "view_wellness": "View wellness check-ins",
    "view_journal": "View journal",
    "view_readings": "View health readings",
    "view_transport": "View transportation status",
    "receive_alerts": "Receive alerts",
    "acknowledge_alerts": "Acknowledge alerts",
    "manage_tasks": "Manage shared tasks",
    "handoff": "Participate in handoffs",
    "view_devices": "View simulated Home Hub and Car Hub status",
    **PHASE5_PERMISSION_LABELS,
}

CIRCLE_STATUSES = frozenset({"invited", "active", "revoked"})
REMINDER_KINDS = frozenset({"medication", "appointment", "wellness", "custom"})
REMINDER_STATUSES = frozenset({"scheduled", "due", "acknowledged", "snoozed", "cancelled"})
ALERT_TYPES = frozenset({
    "caregiver_invite",
    "wellness_shared",
    "reminder_due",
    "handoff",
    "sos_demonstration",
    "task_assigned",
    "safety_event",
})
ALERT_SEVERITIES = frozenset({"info", "attention", "urgent_demo"})
ALERT_STATUSES = frozenset({"open", "acknowledged", "escalated_demo", "closed"})
TRANSPORT_STATUSES = frozenset({"not_connected", "requested", "status_only"})
SOS_STATUSES = frozenset({"draft", "confirmed", "acknowledged", "closed"})
HANDOFF_STATUSES = frozenset({"pending", "accepted", "declined"})
TASK_STATUSES = frozenset({"open", "completed", "cancelled"})

DEFAULT_ACCESSIBILITY = {
    "large_text": True,
    "high_contrast": False,
    "reduce_motion": False,
    "screen_reader_hints": True,
}

CONSENT_FOR_FEATURE = {
    "medications": "reminders",
    "reminders": "reminders",
    "appointments": "reminders",
    "wellness": "wellness_checkins",
    "journal": "journal",
    "readings": "health_readings",
    "transport": "transport_status",
    "ai": "ai_conversation",
    "sos": "sos_demonstration",
    "circle": "caregiver_sharing",
    "coordination": "care_cloud_use",
    "notifications": "caregiver_notifications",
    "device": "simulated_device_ingest",
    "hardware": "hardware_simulation",
    "video": "video_session_simulation",
    "connected_devices": "connected_device_readings",
    "home_tests": "home_test_status",
    "result_documents": "laboratory_result_documents",
}
