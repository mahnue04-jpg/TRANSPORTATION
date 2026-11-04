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


def test_sendgrid_unexpected_status_is_not_success():
    class RejectedResponse(AcceptedResponse):
        status = 200

    with patch.dict("os.environ", {
        "SENDGRID_API_KEY": "placeholder",
        "SENDGRID_FROM_EMAIL": "noreply@example.org",
    }):
        with patch.object(reset, "urlopen", return_value=RejectedResponse()):
            result = reset._send_reset_email(
                to_email="person@example.org",
                reset_url="https://example.org/nova/reset-password",
            )
    assert result == {"attempted": True, "sent": False, "reason": "send_failed"}


def test_sendgrid_logs_do_not_contain_reset_token(caplog):
    import logging

    marker = "unique-private-reset-token"
    with patch.dict("os.environ", {
        "SENDGRID_API_KEY": "placeholder",
        "SENDGRID_FROM_EMAIL": "noreply@example.org",
    }):
        with patch.object(reset, "urlopen", side_effect=OSError(marker)):
            with caplog.at_level(logging.WARNING, logger="amicor.auth.password_reset"):
                reset._send_reset_email(
                    to_email="person@example.org",
                    reset_url="https://example.org/nova/reset-password?token=" + marker,
                )
    assert marker not in caplog.text
    assert "password_reset_email_failed" in caplog.text


def test_no_provider_configured_skips_delivery():
    config = {
        "SENDGRID_API_KEY": "",
        "SENDGRID_FROM_EMAIL": "",
        "AUTH_SMTP_HOST": "",
        "MARKETING_SMTP_HOST": "",
        "AUTH_SMTP_FROM": "",
        "MARKETING_SMTP_FROM": "",
    }
    with patch.dict("os.environ", config):
        with patch.object(reset, "urlopen") as send:
            result = reset._send_reset_email(
                to_email="person@example.org",
                reset_url="https://example.org/nova/reset-password",
            )
    assert result == {"attempted": False, "sent": False, "reason": "not_configured"}
    send.assert_not_called()


def test_https_request_uses_verified_sender_and_private_authorization():
    import json

    with patch.dict("os.environ", {
        "SENDGRID_API_KEY": "placeholder-test-api-key",
        "SENDGRID_FROM_EMAIL": "noreply@example.org",
    }):
        with patch.object(reset, "urlopen", return_value=AcceptedResponse()) as send:
            with patch.object(reset.smtplib, "SMTP") as smtp:
                reset._send_reset_email(
                    to_email="person@example.org",
                    reset_url="https://example.org/nova/reset-password?token=one-time-value",
                )
    request = send.call_args.args[0]
    assert request.full_url == "https://api.sendgrid.com/v3/mail/send"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer placeholder-test-api-key"
    payload = json.loads(request.data)
    assert payload["from"]["email"] == "noreply@example.org"
    assert payload["personalizations"][0]["to"][0]["email"] == "person@example.org"
    assert "one-time-value" in payload["content"][0]["value"]
    smtp.assert_not_called()


def test_incomplete_sendgrid_config_does_not_send_https():
    config = {
        "SENDGRID_API_KEY": "placeholder",
        "SENDGRID_FROM_EMAIL": "",
        "AUTH_SMTP_HOST": "",
        "MARKETING_SMTP_HOST": "",
        "AUTH_SMTP_FROM": "",
        "MARKETING_SMTP_FROM": "",
    }
    with patch.dict("os.environ", config):
        with patch.object(reset, "urlopen") as send:
            result = reset._send_reset_email(
                to_email="person@example.org",
                reset_url="https://example.org/nova/reset-password",
            )
    assert result["reason"] == "not_configured"
    send.assert_not_called()


def test_partial_https_config_prevents_smtp_fallback():
    config = {
        "SENDGRID_API_KEY": "placeholder",
        "SENDGRID_FROM_EMAIL": "",
        "AUTH_SMTP_HOST": "smtp.example.org",
        "AUTH_SMTP_FROM": "noreply@example.org",
    }
    with patch.dict("os.environ", config):
        with patch.object(reset.smtplib, "SMTP") as smtp:
            with patch.object(reset, "urlopen") as https_send:
                result = reset._send_reset_email(
                    to_email="person@example.org",
                    reset_url="https://example.org/nova/reset-password",
                )
    assert result == {"attempted": False, "sent": False, "reason": "not_configured"}
    smtp.assert_not_called()
    https_send.assert_not_called()


def test_plaintext_reset_capture_rejected_in_production():
    """An accidental production flag must never expose a password reset token."""
    reset.clear_test_reset_capture()
    for environment_name in ("APP_ENV", "AMICOR_ENVIRONMENT", "ENVIRONMENT", "FLASK_ENV"):
        with patch.dict("os.environ", {
            "APP_ENV": "",
            "AMICOR_ENVIRONMENT": "",
            "ENVIRONMENT": "",
            "FLASK_ENV": "",
            environment_name: "production",
            "AMICOR_PASSWORD_RESET_TEST_CAPTURE": "true",
        }):
            assert reset._test_capture_enabled() is False
            assert reset.get_test_reset_token("person@example.org") is None


def test_plaintext_reset_capture_is_opt_in_for_local_tests():
    with patch.dict("os.environ", {
        "APP_ENV": "test",
        "AMICOR_ENVIRONMENT": "",
        "ENVIRONMENT": "",
        "FLASK_ENV": "",
        "AMICOR_PASSWORD_RESET_TEST_CAPTURE": "true",
    }):
        assert reset._test_capture_enabled() is True
    with patch.dict("os.environ", {
        "APP_ENV": "test",
        "AMICOR_ENVIRONMENT": "",
        "ENVIRONMENT": "",
        "FLASK_ENV": "",
        "AMICOR_PASSWORD_RESET_TEST_CAPTURE": "",
    }):
        assert reset._test_capture_enabled() is False


def test_password_reset_request_creates_schema_on_session_database():
    """The request must use its own isolated database, not the app default engine."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session

    isolated = create_engine("sqlite+pysqlite:///:memory:")
    try:
        assert "password_reset_tokens" not in inspect(isolated).get_table_names()
        with Session(isolated) as db:
            result = reset.request_password_reset(db, email="not-an-email")
        assert result == {"status": "ok", "message": reset.GENERIC_REQUEST_MESSAGE}
        assert "password_reset_tokens" in inspect(isolated).get_table_names()
    finally:
        isolated.dispose()


def test_reset_tokens_are_hashed_and_not_recoverable_from_digest():
    from app.password_reset_service import hash_reset_token

    secret = "test-only-one-time-token-value"
    digest = hash_reset_token(secret)
    assert len(digest) == 64
    assert digest != secret
    assert digest == hash_reset_token(secret)
    assert digest != hash_reset_token(secret + "-changed")


def test_reset_token_expiry_rejects_expired_and_naive_timestamps():
    from datetime import datetime, timedelta, timezone
    from app.password_reset import token_is_expired

    current = datetime.now(timezone.utc)
    assert token_is_expired(current - timedelta(minutes=1))
    assert not token_is_expired(current + timedelta(minutes=30))
    assert token_is_expired((current - timedelta(minutes=1)).replace(tzinfo=None))


def test_failed_delivery_preserves_previous_reset_tokens():
    from types import SimpleNamespace
    from unittest.mock import Mock

    replacement = SimpleNamespace(email="person@example.org", token_hash="new")
    db = Mock()
    reset._finalize_reset_delivery(db, new_token=replacement, accepted=False)
    db.query.assert_not_called()
    db.delete.assert_called_once_with(replacement)
    db.commit.assert_called_once()


def test_accepted_delivery_retires_all_competing_reset_tokens():
    from types import SimpleNamespace
    from unittest.mock import Mock, call
    from app.db.models import User as UserModel
    from app.password_reset import PasswordResetToken

    from app.password_reset import default_reset_expiry

    replacement = SimpleNamespace(
        email="person@example.org",
        token_hash="new",
        used_at=None,
        expires_at=default_reset_expiry(),
    )
    db = Mock()
    account_lookup = Mock()
    account_lookup.filter.return_value.with_for_update.return_value.one_or_none.return_value = object()
    token_update = Mock()
    db.query.side_effect = [account_lookup, token_update]
    reset._finalize_reset_delivery(db, new_token=replacement, accepted=True)
    assert db.query.call_args_list == [call(UserModel), call(PasswordResetToken)]
    account_lookup.filter.return_value.with_for_update.assert_called_once_with()
    token_update.filter.return_value.update.assert_called_once()
    db.delete.assert_not_called()
    db.commit.assert_called_once()


def test_accepted_delivery_removes_token_if_account_was_deleted():
    from types import SimpleNamespace
    from unittest.mock import Mock

    replacement = SimpleNamespace(email="person@example.org", token_hash="new")
    db = Mock()
    db.query.return_value.filter.return_value.with_for_update.return_value.one_or_none.return_value = None
    reset._finalize_reset_delivery(db, new_token=replacement, accepted=True)
    db.delete.assert_called_once_with(replacement)
    db.commit.assert_called_once()


def test_smtp_failure_logs_no_exception_secrets(caplog):
    import logging

    marker = "private-smtp-credential-and-reset-token"
    env = {
        "SENDGRID_API_KEY": "",
        "SENDGRID_FROM_EMAIL": "",
        "AUTH_SMTP_HOST": "smtp.example.org",
        "AUTH_SMTP_FROM": "noreply@example.org",
    }
    with patch.dict("os.environ", env):
        with patch.object(reset.smtplib, "SMTP", side_effect=OSError(marker)):
            with caplog.at_level(logging.WARNING, logger="amicor.auth.password_reset"):
                result = reset._send_reset_email(
                    to_email="person@example.org",
                    reset_url="https://example.org/nova/reset-password?token=" + marker,
                )
    assert result == {"attempted": True, "sent": False, "reason": "send_failed"}
    assert marker not in caplog.text
    assert "password_reset_email_failed provider=smtp" in caplog.text


def test_reset_origin_rejects_insecure_or_malformed_destinations():
    invalid = (
        "http://example.org",
        "https://user:secret@example.org",
        "https://example.org/redirect",
        "https://example.org/?next=other",
        "https://example.org/#fragment",
        "https://example.org:invalid",
        "https://example.org\nBcc: attacker@example.org",
        "javascript:alert(1)",
        "https://",
    )
    for origin in invalid:
        with patch.dict("os.environ", {"AMICOR_PUBLIC_BASE_URL": origin}):
            assert reset._validated_reset_base_url() is None
    with patch.dict("os.environ", {"AMICOR_PUBLIC_BASE_URL": "https://example.org/"}):
        assert reset._validated_reset_base_url() == "https://example.org"


def test_invalid_origin_never_creates_token_or_sends_email():
    """Request handler checks the destination before persisting any token."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    db = Mock()
    db.get_bind.return_value = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        email="person@example.org", is_active=True, auth_version=0
    )
    with patch.object(reset, "ensure_password_reset_schema"):
        with patch.object(reset, "_validated_reset_base_url", return_value=None):
            with patch.object(reset, "_send_reset_email") as send:
                result = reset.request_password_reset(db, email="person@example.org")
    assert result == {"status": "ok", "message": reset.GENERIC_REQUEST_MESSAGE}
    db.add.assert_not_called()
    send.assert_not_called()


def test_staging_requires_explicit_public_reset_origin():
    config = {
        "APP_ENV": "staging",
        "AMICOR_ENVIRONMENT": "",
        "ENVIRONMENT": "",
        "AMICOR_PUBLIC_BASE_URL": "",
        "NOVA_SIGNUP_PUBLIC_BASE_URL": "https://amicor-health-isf-py.onrender.com",
    }
    with patch.dict("os.environ", config):
        assert reset._validated_reset_base_url() is None
    config["AMICOR_PUBLIC_BASE_URL"] = "https://staging.example.org"
    with patch.dict("os.environ", config):
        assert reset._validated_reset_base_url() == "https://staging.example.org"


def test_plaintext_capture_is_disabled_in_staging_even_if_flag_is_set():
    configurations = (
        {"APP_ENV": "staging", "AMICOR_ENVIRONMENT": ""},
        {"APP_ENV": "", "AMICOR_ENVIRONMENT": ""},
        {"APP_ENV": "development", "AMICOR_ENVIRONMENT": ""},
    )
    for overrides in configurations:
        env = {
            "APP_ENV": "",
            "AMICOR_ENVIRONMENT": "",
            "ENVIRONMENT": "",
            "FLASK_ENV": "",
            "AMICOR_PASSWORD_RESET_TEST_CAPTURE": "true",
            **overrides,
        }
        with patch.dict("os.environ", env):
            assert reset._test_capture_enabled() is False
            assert reset.get_test_reset_token("person@example.org") is None
