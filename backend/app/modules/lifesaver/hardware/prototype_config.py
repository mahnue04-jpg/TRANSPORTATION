"""Local prototype hardware profile. Not bound to one manufacturer."""
from __future__ import annotations

HOME_HUB_PROTOTYPE = {
    "profile": "home_hub_prototype",
    "controller_class": "raspberry_pi_class",
    "modules": (
        "camera_module",
        "microphone",
        "speaker",
        "rotating_base_motor",
        "power_module",
        "optional_battery_backup",
        "optional_environmental_sensors",
    ),
    "manufacturer_locked": False,
    "vehicle_control": False,
    "medical_certified": False,
}

CAR_HUB_PROTOTYPE = {
    "profile": "car_hub_prototype",
    "controller_class": "raspberry_pi_class_or_equivalent",
    "modules": (
        "display",
        "speaker",
        "microphone",
        "local_connectivity",
        "optional_gps_later",
    ),
    "manufacturer_locked": False,
    "vehicle_control": False,
    "medical_certified": False,
}


def prototype_for(device_type: str) -> dict:
    if device_type == "HOME_HUB":
        return dict(HOME_HUB_PROTOTYPE)
    if device_type == "CAR_HUB":
        return dict(CAR_HUB_PROTOTYPE)
    return {"profile": "unknown", "manufacturer_locked": False}
