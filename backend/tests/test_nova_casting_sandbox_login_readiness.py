"""Login success stays separate from a disabled casting sandbox.

A 200 login keeps the session. Disabled readiness is informational.
A 401 and an existing-email 409 stay request errors and do not create a session.
No mail, SMS, or WhatsApp transport is opened.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "sandbox-access-token"
REFRESH = "sandbox-refresh-token"
PASSWORD = "correct-password"


class _Log:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.authorization: list[str] = []

    def reset(self) -> None:
        self.calls.clear()
        self.authorization.clear()

    def api_calls(self) -> list[tuple[str, str]]:
        return [item for item in self.calls if item[1].startswith("/api/")]


LOG = _Log()


def _app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def record(request: Request, call_next):
        LOG.calls.append((request.method, request.url.path))
        return await call_next(request)

    @app.post("/api/auth/login")
    async def login(request: Request):
        payload = await request.json()
        if payload.get("password") != PASSWORD:
            return JSONResponse({"detail": "Invalid email or password"}, status_code=401)
        return {"access_token": TOKEN, "refresh_token": REFRESH}

    @app.get("/api/nova/casting/readiness")
    async def readiness(request: Request):
        LOG.authorization.append(request.headers.get("authorization") or "")
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return {
            "enabled": False,
            "applications_enabled": False,
            "media_uploads_enabled": False,
            "sandbox_writes_enabled": False,
            "sandbox_private_media_enabled": False,
            "antivirus_ready": False,
            "scanner_mode": "structural",
        }

    @app.post("/api/nova/signup/free")
    async def signup():
        return JSONResponse({"detail": "Email already registered"}, status_code=409)

    @app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def blocked(full_path: str):
        return JSONResponse({"detail": f"external action blocked: {full_path}"}, status_code=500)

    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    return app


def _start_server():
    uvicorn = pytest.importorskip("uvicorn")
    config = uvicorn.Config(_app(), host="127.0.0.1", port=8791, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(80):
        if server.started:
            break
        thread.join(0.1)
    assert server.started
    return server, thread


def _session(page) -> dict:
    return page.evaluate(
        """() => ({
          banner: document.getElementById("banner").textContent,
          bannerClass: document.getElementById("banner").className,
          status: document.getElementById("status").textContent,
          token: localStorage.getItem("amicor_nova_creative_token"),
          refresh: sessionStorage.getItem("amicor_nova_creative_refresh")
        })"""
    )


def _expect_readiness(page, selector: str) -> None:
    with page.expect_response(
        lambda response: response.url.endswith("/api/nova/casting/readiness") and response.status == 200
    ):
        page.click(selector)
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Sandbox workflows are off.'"
    )


@pytest.fixture(scope="module")
def sandbox_server():
    server, thread = _start_server()
    try:
        yield "http://127.0.0.1:8791"
    finally:
        server.should_exit = True
        thread.join(3)


@pytest.fixture
def page(sandbox_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(base_url=sandbox_server)
        current = context.new_page()
        try:
            yield current
        finally:
            browser.close()


def test_login_200_with_disabled_readiness_keeps_session(page) -> None:
    LOG.reset()
    page.goto("/static/nova-creative/casting-sandbox.html", wait_until="domcontentloaded")
    page.fill("#login-email", "owner@example.com")
    page.fill("#login-password", PASSWORD)
    with page.expect_response(lambda response: response.url.endswith("/api/nova/casting/readiness")):
        page.click("#sign-in")
    page.wait_for_selector("#banner:has-text('Signed in.')")
    state = _session(page)
    assert state["status"] == "Sandbox workflows are off."
    assert "Request error" not in state["status"]
    assert "Request error" not in state["banner"]
    assert "error" not in state["bannerClass"].split()
    assert "Sandbox workflows are off." in state["banner"]
    assert "Nothing was submitted." in state["banner"]
    assert state["token"] == TOKEN
    assert state["refresh"] == REFRESH
    assert page.input_value("#login-password") == ""
    assert TOKEN not in page.inner_text("body")
    assert f"Bearer {TOKEN}" in LOG.authorization

    page.fill("#organization-id", "org-disabled")
    page.fill("#campaign-title", "Harborlight")
    page.fill("#faq-question", "When is the fictional callback?")
    for selector in ("#create-organization", "#create-campaign", "#ask-faq", "#journey-mock", "#draft-invite"):
        _expect_readiness(page, selector)

    state = _session(page)
    assert state["token"] == TOKEN
    assert state["refresh"] == REFRESH
    assert state["status"] == "Sandbox workflows are off."
    assert "error" not in state["bannerClass"].split()
    assert "Request error" not in state["banner"]
    posts = [path for method, path in LOG.api_calls() if method != "GET"]
    assert posts == ["/api/auth/login"]
    gets = {path for method, path in LOG.api_calls() if method == "GET"}
    assert gets == {"/api/nova/casting/readiness"}
    assert "External delivery: false" in page.inner_text("#faq-status")


def test_login_401_is_a_request_error_without_a_session(page) -> None:
    LOG.reset()
    page.goto("/static/nova-creative/casting-sandbox.html", wait_until="domcontentloaded")
    page.fill("#login-email", "owner@example.com")
    page.fill("#login-password", "wrong-password")
    with page.expect_response(lambda response: response.url.endswith("/api/auth/login") and response.status == 401):
        page.click("#sign-in")
    page.wait_for_selector("#banner:has-text('Invalid email or password')")
    state = _session(page)
    assert state["status"] == "Request error"
    assert "error" in state["bannerClass"].split()
    assert state["token"] in (None, "")
    assert state["refresh"] in (None, "")
    assert "Signed in." not in state["banner"]
    assert [item for item in LOG.api_calls() if item[0] != "GET"] == [("POST", "/api/auth/login")]
    assert not any(path.endswith("/readiness") for _method, path in LOG.api_calls())


def test_existing_email_409_does_not_create_a_session(page) -> None:
    LOG.reset()
    page.goto("/static/nova-creative/casting-sandbox.html", wait_until="domcontentloaded")
    password = "Existing1!pass"
    page.fill("#signup-business", "Harbor Existing")
    page.fill("#signup-contact", "Jordan Hale")
    page.fill("#signup-email", "existing.person@example.com")
    page.fill("#signup-phone", "6125550144")
    page.fill("#signup-industry", "creative")
    page.fill("#signup-password", password)
    page.fill("#signup-confirm", password)
    page.check("#signup-terms")
    with page.expect_response(lambda response: response.url.endswith("/api/nova/signup/free") and response.status == 409):
        page.click("#create-account")
    page.wait_for_selector("#banner:has-text('This email already has a Nova account')")
    state = _session(page)
    assert "Sign in instead. Nothing was created." in state["banner"]
    assert state["status"] == "Request error"
    assert "error" in state["bannerClass"].split()
    assert state["token"] in (None, "")
    assert state["refresh"] in (None, "")
    assert page.input_value("#signup-password") == ""
    assert page.input_value("#signup-confirm") == ""
    assert password not in page.inner_text("body")
    assert LOG.api_calls() == [("POST", "/api/nova/signup/free")]
