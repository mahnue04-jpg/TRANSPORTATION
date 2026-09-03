"""Helpers for the applicant work-setup APIs. Uses synthetic applications only."""
from __future__ import annotations

from app.modules.platform_ops.onboarding.stripe_connect import (
    FakeStripeConnectClient,
    set_stripe_connect_client_override,
)


def complete_secure_work_setup(
    client,
    app_id: str,
    token: str,
    *,
    legal_name: str = "Test Driver",
    fake: FakeStripeConnectClient | None = None,
) -> dict:
    headers = {"X-Applicant-Token": token}
    stripe = fake or FakeStripeConnectClient()
    set_stripe_connect_client_override(stripe)
    try:
        current = client.get(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup",
            headers=headers,
        )
        assert current.status_code == 200, current.text
        status = current.json()
        if not status["agreement"]["complete"]:
            signed = client.post(
                f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/agreement/sign",
                headers=headers,
                json={"typed_signature": legal_name, "accepted": True},
            )
            assert signed.status_code == 200, signed.text
        if not status["tax"]["complete"]:
            w9 = client.post(
                f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/w9",
                headers=headers,
                json={
                    "tax_classification": "individual",
                    "legal_name": legal_name,
                    "certify_accurate": True,
                    "certify_us_person": True,
                },
            )
            assert w9.status_code == 200, w9.text
        if not status["payout"]["complete"]:
            start = client.post(
                f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/payout/start",
                headers=headers,
                json={
                    "return_url": "https://amicor.test/driver-apply?work_setup=stripe_return",
                    "refresh_url": "https://amicor.test/driver-apply?work_setup=stripe_refresh",
                },
            )
            assert start.status_code == 200, start.text
            stripe.mark_complete()
            refreshed = client.post(
                f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/payout/refresh",
                headers=headers,
            )
            assert refreshed.status_code == 200, refreshed.text
            return refreshed.json()
        latest = client.get(
            f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup",
            headers=headers,
        )
        assert latest.status_code == 200, latest.text
        return latest.json()
    finally:
        if fake is None:
            set_stripe_connect_client_override(None)
