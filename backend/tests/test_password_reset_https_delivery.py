"""Offline regression tests for Nova password-reset HTTPS transport."""
from unittest.mock import patch

from app import password_reset_service as reset


class AcceptedResponse:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_https_provider_accepts_message():
    with patch.dict("os.environ", {
        "SENDGRID_API_KEY": "placeholder",
        "SENDGRID_FROM_EMAIL": "noreply@example.org",
    }):
        with patch.object(reset, "urlopen", return_value=AcceptedResponse()) as send:
            result = reset._send_reset_email(
                to_email="person@example.org",
                reset_url="https://example.org/nova/reset-password",
            )
    assert result["sent"] is True
    assert result["reason"] == "accepted"
    assert send.call_count == 1


def test_https_failure_returns_generic_status():
    with patch.dict("os.environ", {
        "SENDGRID_API_KEY": "placeholder",
        "SENDGRID_FROM_EMAIL": "noreply@example.org",
    }):
        with patch.object(reset, "urlopen", side_effect=OSError("offline")):
            result = reset._send_reset_email(
                to_email="person@example.org",
                reset_url="https://example.org/nova/reset-password",
            )
    assert result["sent"] is False
    assert result["reason"] == "send_failed"


def test_public_url_fallback():
    variables = {
        "AMICOR_PUBLIC_BASE_URL": "",
        "NOVA_SIGNUP_PUBLIC_BASE_URL": "",
        "PUBLIC_BASE_URL": "",
        "AMICOR_PUBLIC_URL": "https://amicor-health-isf.onrender.com/",
    }
    with patch.dict("os.environ", variables):
        assert reset._public_base_url() == "https://amicor-health-isf.onrender.com"
