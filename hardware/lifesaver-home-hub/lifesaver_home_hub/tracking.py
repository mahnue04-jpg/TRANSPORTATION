"""Abstract future tracking contract. No biometrics or identity matching."""

STATES = (
    "TRACKING_DISABLED",
    "TARGET_NOT_PRESENT",
    "TARGET_PRESENT",
    "TRACKING_AVAILABLE",
    "TRACKING_ACTIVE",
    "TRACKING_PAUSED",
    "PRIVACY_BLOCKED",
    "LOST_TARGET",
)
