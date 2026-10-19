"""Desktop and phone walkthrough of casting sandbox account forms.

The reset token is read from the test capture, never from the page text.
No mail transport is opened.
"""
from __future__ import annotations

import os
import smtplib
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

from app.helpers import uuid4
from app.password_reset_service import clear_test_reset_capture, get_test_reset_token


def _forbid_mail():
    original = (smtplib.SMTP, smtplib.SMTP_SSL)

    def opened(*_args, **_kwargs):
        raise AssertionError("outbound mail transport opened")

    smtplib.SMTP = opened
    smtplib.SMTP_SSL = opened
    return original


def _restore_mail(original) -> None:
    smtplib.SMTP, smtplib.SMTP_SSL = original


def _enable() -> dict[str, str | None]:
    previous = {}
    updates = {
        "NOVA_CASTING_STAGING_READS": "true",
        "AMICOR_ENVIRONMENT": "disposable",
        "ENVIRONMENT": "disposable",
        "APP_ENV": "disposable",
        "AMICOR_PASSWORD_RESET_TEST_CAPTURE": "1",
    }
    clears = (
        "AUTH_SMTP_HOST",
        "AUTH_SMTP_FROM",
        "MARKETING_SMTP_HOST",
        "MARKETING_SMTP_FROM",
        "NOVA_CASTING_SMS_PROVIDER",
        "NOVA_CASTING_WHATSAPP_PROVIDER",
    )
    for name, value in updates.items():
        previous[name] = os.environ.get(name)
        os.environ[name] = value
    for name in clears:
        previous[name] = os.environ.get(name)
        os.environ.pop(name, None)
    return previous


def _restore(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _account(prefix: str) -> dict[str, str]:
    return {
        "business": f"Harbor {prefix} {uuid4().replace('-', '')[:6]}",
        "contact": "Jordan Hale",
        "email": f"casting.browser.{prefix}.{uuid4().replace('-', '')[:8]}@example.com",
        "phone": "6125550144",
        "password": f"Browser1!{uuid4().replace('-', '')[:6]}",
        "org": f"Studio {uuid4().replace('-', '')[:8]}",
    }


def _fill_signup(page, account: dict[str, str]) -> None:
    page.fill("#signup-business", account["business"])
    page.fill("#signup-contact", account["contact"])
    page.fill("#signup-email", account["email"])
    page.fill("#signup-phone", account["phone"])
    page.fill("#signup-industry", "creative")
    page.fill("#signup-password", account["password"])
    page.fill("#signup-confirm", account["password"])
    page.check("#signup-terms")


def _browser_app():
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from app.auth import router as auth_router
    from app.core.nova.creative_studio.casting_router_draft import router as casting_router
    from app.core.nova.signup.router import router as signup_router
    from tests.test_nova_casting_sandbox_accounts import _ensure_casting_tables

    _ensure_casting_tables()
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(signup_router)
    app.include_router(casting_router)
    static_dir = Path(__file__).resolve().parents[1] / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


def test_account_forms_desktop_and_phone():
    uvicorn = pytest.importorskip("uvicorn")
    app = _browser_app()

    mail = _forbid_mail()
    previous = _enable()
    clear_test_reset_capture()
    config = uvicorn.Config(app, host="127.0.0.1", port=8773, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(80):
        if server.started:
            break
        thread.join(0.1)
    assert server.started
    shots = Path("/opt/cursor/artifacts/casting-accounts")
    shots.mkdir(parents=True, exist_ok=True)
    desktop_account = _account("desk")
    phone_account = _account("phone")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            desktop = browser.new_context(viewport={"width": 1280, "height": 900}, base_url="http://127.0.0.1:8773")
            page = desktop.new_page()
            page.goto("/static/nova-creative/casting-sandbox.html", wait_until="domcontentloaded")
            assert page.is_visible("#create-account")
            assert page.is_visible("#send-reset")
            assert page.is_visible("#update-password")
            assert page.get_by_text("Sign in with Google").count() == 0
            _fill_signup(page, desktop_account)
            page.click("#create-account")
            page.wait_for_selector("#banner:has-text('Nova account created and signed in')")
            assert desktop_account["password"] not in page.inner_text("body")
            page.fill("#organization-name", desktop_account["org"])
            page.click("#create-organization")
            page.wait_for_selector("#banner:has-text('Sandbox organization ready')")
            org_id = page.input_value("#organization-id")
            assert org_id
            page.click("#sign-out")
            page.wait_for_selector("#banner:has-text('Signed out')")
            page.fill("#login-email", desktop_account["email"])
            page.fill("#login-password", desktop_account["password"])
            page.click("#sign-in")
            page.wait_for_selector("#status:has-text('Ready')")
            page.fill("#forgot-email", desktop_account["email"])
            page.click("#send-reset")
            page.wait_for_selector("#reset-delivery:has-text('No message was sent')")
            assert "have been sent" not in page.inner_text("#reset-delivery")
            token = get_test_reset_token(desktop_account["email"])
            assert token
            assert token not in page.inner_text("body")
            new_password = f"Browser2!{uuid4().replace('-', '')[:6]}"
            page.fill("#reset-token", token)
            page.fill("#reset-password", new_password)
            page.fill("#reset-confirm", new_password)
            page.click("#update-password")
            page.wait_for_selector("#banner:has-text('Password updated')")
            assert token not in page.inner_text("#banner")
            page.fill("#login-email", desktop_account["email"])
            page.fill("#login-password", new_password)
            page.click("#sign-in")
            page.wait_for_selector("#status:has-text('Ready')")
            page.screenshot(path=str(shots / "desktop-signed-in.png"), full_page=True)

            phone = browser.new_context(
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                base_url="http://127.0.0.1:8773",
            )
            mobile = phone.new_page()
            mobile.goto("/static/nova-creative/casting-sandbox.html", wait_until="domcontentloaded")
            assert mobile.is_visible("#create-account")
            assert mobile.is_visible("#send-reset")
            assert mobile.is_visible("#update-password")
            fits = mobile.evaluate(
                "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
            )
            assert fits
            tall = mobile.evaluate(
                """() => {
                  const button = document.getElementById("create-account");
                  return button.getBoundingClientRect().height >= 44;
                }"""
            )
            assert tall
            _fill_signup(mobile, phone_account)
            mobile.click("#create-account")
            mobile.wait_for_selector("#banner:has-text('Nova account created and signed in')")
            mobile.fill("#organization-name", phone_account["org"])
            mobile.click("#create-organization")
            mobile.wait_for_selector("#banner:has-text('Sandbox organization ready')")
            mobile.click("#sign-out")
            mobile.wait_for_selector("#banner:has-text('Signed out')")
            mobile.fill("#login-email", phone_account["email"])
            mobile.fill("#login-password", phone_account["password"])
            mobile.click("#sign-in")
            mobile.wait_for_selector("#status:has-text('Ready')")
            mobile.fill("#forgot-email", "nobody-phone@example.com")
            mobile.click("#send-reset")
            mobile.wait_for_selector("#reset-delivery:has-text('No message was sent')")
            mobile.screenshot(path=str(shots / "iphone-account.png"), full_page=True)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(3)
        _restore(previous)
        _restore_mail(mail)
