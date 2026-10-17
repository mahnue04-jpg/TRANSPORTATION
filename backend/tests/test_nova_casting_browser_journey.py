"""Authenticated browser walkthrough of the sandbox casting journey.

Skipped only when Playwright is not installed. The server is disposable SQLite.
No mail transport is opened.
"""
import os
import smtplib
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORG = "org-a"
CAMPAIGN = "campaign-1"
EMAIL = "organizer@example.invalid"
PASSWORD = "sandbox-pass"


def _forbid_mail():
    def opened(*_args, **_kwargs):
        raise AssertionError("outbound mail transport opened")

    smtplib.SMTP = opened
    smtplib.SMTP_SSL = opened


def _build_app(tmp_path):
    os.environ["NOVA_CASTING_STAGING_READS"] = "true"
    os.environ["AMICOR_ENVIRONMENT"] = "disposable"
    os.environ["ENVIRONMENT"] = "disposable"
    os.environ["APP_ENV"] = "disposable"
    os.environ["JWT_SECRET"] = "test-only"
    os.environ["SECRET_KEY"] = "test-only"
    os.environ.pop("NOVA_CASTING_SMS_PROVIDER", None)
    os.environ.pop("NOVA_CASTING_WHATSAPP_PROVIDER", None)
    _forbid_mail()
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.staticfiles import StaticFiles

    from app.auth import UserContext, get_current_user_context
    from app.core.nova.creative_studio import casting_db_models, casting_pilot_models
    from app.core.nova.creative_studio.casting_router_draft import router
    from app.db.models import User

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'browser.db'}", connect_args={"check_same_thread": False})

    @sa.event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    tables = [
        User.__table__,
        casting_db_models.NovaCastingOrganization.__table__,
        casting_db_models.NovaCastingMembership.__table__,
        casting_db_models.NovaCastingCampaign.__table__,
        casting_db_models.NovaCastingApplication.__table__,
        casting_pilot_models.NovaCastingRole.__table__,
        casting_pilot_models.NovaCastingIntake.__table__,
        casting_pilot_models.NovaCastingRubric.__table__,
        casting_pilot_models.NovaCastingPilotMessage.__table__,
        casting_pilot_models.NovaCastingSuppression.__table__,
        casting_pilot_models.NovaCastingSchedule.__table__,
        casting_pilot_models.NovaCastingPilotAudit.__table__,
        casting_pilot_models.NovaCastingInvite.__table__,
        casting_pilot_models.NovaCastingMockAttempt.__table__,
        casting_pilot_models.NovaCastingMockMedia.__table__,
        casting_pilot_models.NovaCastingJourneyAudit.__table__,
    ]
    for table in tables:
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    db.add(User(
        id="organizer", email=EMAIL, hashed_password="not-a-login",
        role="staff", organization_id="tenant-a", is_active=True, is_verified=True,
    ))
    db.add(casting_db_models.NovaCastingOrganization(
        id=ORG, nova_tenant_id="tenant-a", name="Harborlight samples",
        verification_status="VERIFIED", created_at="2026-10-01T00:00:00+00:00",
    ))
    db.flush()
    db.add(casting_db_models.NovaCastingMembership(
        id="member-organizer", nova_tenant_id="tenant-a", organization_id=ORG,
        user_id="organizer", casting_role="organizer", active=True,
        created_at="2026-10-01T00:00:00+00:00",
    ))
    db.add(casting_db_models.NovaCastingCampaign(
        id=CAMPAIGN, owner_id=ORG, title="Harborlight", category="film",
        status="DRAFT", minimum_age=18, created_at="2026-10-01T00:00:00+00:00",
    ))
    db.commit()
    db.close()
    import app.db.session as session_module
    session_module.SessionLocal = Session
    app = FastAPI()
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.post("/api/auth/login")
    def login(payload: dict):
        if payload.get("email") != EMAIL or payload.get("password") != PASSWORD:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        return {"access_token": "organizer"}

    def current_user(request: Request):
        token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if token != "organizer":
            raise HTTPException(status_code=401, detail="Authentication required")
        return UserContext(
            user_id="organizer", email=EMAIL, role="staff", organization_id="tenant-a",
        )

    app.dependency_overrides[get_current_user_context] = current_user
    return app, engine


def _sign_in(page):
    page.goto("/static/nova-creative/casting-sandbox.html", wait_until="domcontentloaded")
    page.fill("#login-email", EMAIL)
    page.fill("#login-password", PASSWORD)
    page.click("#sign-in")
    page.wait_for_selector("#status:has-text('Ready')")
    page.fill("#organization-id", ORG)
    page.fill("#application-campaign", CAMPAIGN)


def test_browser_journey_desktop_and_iphone(tmp_path):
    uvicorn = pytest.importorskip("uvicorn")
    import threading

    app, engine = _build_app(tmp_path)
    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        thread.join(0.1)
    assert server.started
    shots = Path("/opt/cursor/artifacts/casting-journey")
    shots.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            desktop = browser.new_context(viewport={"width": 1280, "height": 900}, base_url="http://127.0.0.1:8765")
            page = desktop.new_page()
            _sign_in(page)
            page.fill("#pilot-deadline", "2027-12-01T18:00")
            page.click("#save-pilot-role")
            page.wait_for_selector("#banner:has-text('Role saved')")
            page.click("#journey-invite")
            page.wait_for_selector("#journey-status:has-text('Nothing was sent')")
            token = page.input_value("#journey-token")
            assert token
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector("#journey-status:has-text('Invitation reloaded')")
            assert page.input_value("#journey-token") == token
            page.screenshot(path=str(shots / "desktop-reloaded.png"), full_page=True)
            page.click("#journey-redeem")
            page.wait_for_selector("#journey-status:has-text('redeemed')")
            page.fill("#pilot-name", "Jordan Hale")
            page.fill("#pilot-email", "jordan.hale@example.invalid")
            page.fill("#pilot-age", "28")
            page.fill("#pilot-link", "https://example.invalid/tape")
            page.fill("#pilot-answer", "Yes")
            page.check("#pilot-consent")
            page.click("#save-pilot-intake")
            page.wait_for_selector("#pilot-receipt:has-text('Receipt')")
            page.click("#submit-pilot-intake")
            page.wait_for_selector("#pilot-receipt:has-text('SUBMITTED')")
            assert "CA-" in page.inner_text("#pilot-receipt")
            page.screenshot(path=str(shots / "desktop-receipt.png"), full_page=True)
            page.click("#pilot-shortlist")
            page.wait_for_selector("#banner:has-text('Shortlist recorded')")
            page.click("#draft-invite")
            page.wait_for_selector("#banner:has-text('No invitation was sent')")
            page.click("#approve-invite")
            page.wait_for_selector("#banner:has-text('Nothing was sent')")
            page.evaluate(
                """async (roleId) => {
                  const headers = { "Content-Type": "application/json", Authorization: "Bearer organizer" };
                  const response = await fetch("/api/nova/casting/organizations/org-a/campaigns/campaign-1/schedule", {
                    method: "POST", headers, body: JSON.stringify({
                      role_id: roleId, timezone: "America/New_York",
                      starts_at: "2026-11-18T15:00:00+00:00", ends_at: "2026-11-18T18:00:00+00:00",
                      location_label: "Fictional reading room",
                      document_url: "https://example.invalid/side.pdf"
                    })
                  });
                  if (!response.ok) throw new Error(await response.text());
                }""",
                page.input_value("#pilot-role-id"),
            )
            page.click("#journey-mock")
            page.wait_for_selector("#journey-status:has-text('mock_accepted')")
            assert "Real delivery: false" in page.inner_text("#journey-status")
            page.click("#load-call-sheet")
            page.wait_for_selector("#banner:has-text('Call sheet loaded')")
            page.click("#journey-export")
            page.wait_for_selector("#journey-status:has-text('Sandbox CSV')")
            page.screenshot(path=str(shots / "desktop-call-sheet.png"), full_page=True)
            page.click("#journey-expired")
            page.wait_for_selector("#journey-status:has-text('Expired invitation stayed closed')")
            page.screenshot(path=str(shots / "desktop-expired.png"), full_page=True)

            phone = browser.new_context(
                viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                base_url="http://127.0.0.1:8765",
            )
            mobile = phone.new_page()
            _sign_in(mobile)
            mobile.click("#reload-pilot")
            mobile.wait_for_selector("#journey-status:has-text('Invitation reloaded')")
            assert mobile.input_value("#journey-token")
            mobile.screenshot(path=str(shots / "iphone-reloaded.png"), full_page=True)
            mobile.click("#journey-expired")
            mobile.wait_for_selector("#journey-status:has-text('Expired invitation stayed closed')")
            mobile.screenshot(path=str(shots / "iphone-expired.png"), full_page=True)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(3)
        engine.dispose()
