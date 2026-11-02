"""Start the temporary voice image only on the approved validation hostname."""
import os
from collections.abc import Mapping

TEST_HOST = "nova-studio-validation-350.onrender.com"
PAID_FLAGS = (
    "NOVA_CREATIVE_IMAGE_LIVE_ENABLED", "NOVA_CREATIVE_VIDEO_LIVE_ENABLED",
    "NOVA_CREATIVE_KLING_LIVE_ENABLED", "NOVA_CREATIVE_VOICE_LIVE_ENABLED",
    "NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED", "NOVA_STRIPE_LIVE_ENABLED",
    "HEALTH_ISF_STRIPE_ENABLED",
)


def validate_environment(env: Mapping[str, str]) -> None:
    if env.get("RENDER_EXTERNAL_HOSTNAME") != TEST_HOST:
        raise RuntimeError("This image is restricted to the approved Nova validation host.")
    if env.get("NOVA_CREATIVE_VOICE_PROVIDER") != "nova_local":
        raise RuntimeError("The test image requires the explicit Nova local voice provider.")
    if env.get("NOVA_LOCAL_VOICE_ENABLED", "").lower() not in {"1", "true"}:
        raise RuntimeError("Nova local voice must be enabled for this test image.")
    if any(env.get(key) != "1" for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")):
        raise RuntimeError("Offline model flags are required for this test image.")
    if any(env.get(key, "").strip().lower() in {"1", "true", "yes", "on"} for key in PAID_FLAGS):
        raise RuntimeError("Paid provider and live billing flags must be OFF for the test image.")


def main():
    validate_environment(os.environ)
    os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0",
                          "--port", os.environ.get("PORT", "10000")])


if __name__ == "__main__":
    main()
