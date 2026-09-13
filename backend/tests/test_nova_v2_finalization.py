"""Nova V2 finalization: every visible tab opens and every control has a real outcome."""
from __future__ import annotations

from pathlib import Path
import re

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

NOVA_TABS = (
    "/nova",
    "/nova/today",
    "/nova/workspace",
    "/nova/communications",
    "/nova/government",
    "/nova/business",
    "/nova/accounting",
    "/nova/accounting/aging",
    "/nova/accounting/trends",
    "/nova/payments/readiness",
    "/nova/freight",
    "/workspace",
    "/app",
)

NOVA_HTML = [
    STATIC / "nova-home" / "index.html",
    STATIC / "nova-today" / "index.html",
    STATIC / "nova-workspace" / "index.html",
    STATIC / "nova-communications" / "index.html",
    STATIC / "nova-government" / "index.html",
    STATIC / "nova-business" / "index.html",
    STATIC / "nova-accounting" / "index.html",
    STATIC / "nova-accounting" / "aging.html",
    STATIC / "nova-accounting" / "trends.html",
    STATIC / "nova-payments" / "index.html",
]

NOVA_CSS = [
    STATIC / "nova-home" / "home.css",
    STATIC / "nova-today" / "today.css",
    STATIC / "nova-workspace" / "workspace.css",
    STATIC / "nova-communications" / "communications.css",
    STATIC / "nova-government" / "government.css",
    STATIC / "nova-business" / "business.css",
    STATIC / "nova-accounting" / "accounting.css",
    STATIC / "nova-payments" / "readiness.css",
]


def _client() -> TestClient:
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema
    from app.db.session import engine, init_platform_db

    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_nova_today_schema(engine)
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_nova_v2_every_tab_opens() -> None:
    client = _client()
    for path in NOVA_TABS:
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200, f"{path} -> {response.status_code}"
        assert "html" in (response.headers.get("content-type") or "").lower()


REQUIRED_NAV = (
    "/nova",
    "/nova/today",
    "/nova/workspace",
    "/nova/communications",
    "/nova/government",
    "/nova/business",
    "/nova/accounting",
    "/nova/accounting/aging",
    "/nova/accounting/trends",
    "/nova/payments/readiness",
    "/nova/freight",
    "/workspace",
    "/app",
)


def test_nova_v2_home_exposes_all_nova_tabs() -> None:
    html = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
    for path in REQUIRED_NAV + ("#web-search", "/nova/workspace#files"):
        assert path in html, path


def test_nova_v2_module_nav_reaches_every_tab() -> None:
    for html_path in NOVA_HTML:
        if html_path.name == "index.html" and html_path.parent.name == "nova-home":
            continue
        text = html_path.read_text(encoding="utf-8")
        for path in REQUIRED_NAV:
            assert path in text, f"{html_path} missing {path}"
        assert "web-search" in text or "#web-search" in text
        assert "#files" in text or "workspace#files" in text


def test_nova_v2_no_dead_placeholder_hrefs() -> None:
    dead = re.compile(r'href=["\']javascript:|href=["\']#["\']')
    for path in NOVA_HTML:
        text = path.read_text(encoding="utf-8")
        assert not dead.search(text), f"placeholder href in {path.name}"
        assert "coming soon" not in text.lower()
        assert "TODO" not in text


def test_nova_v2_buttons_are_wired() -> None:
    allowed_attr = (
        "data-brain",
        "data-approve",
        "data-snooze",
        "data-dismiss",
        "data-review",
        "data-recheck",
        "data-months",
        "data-window",
        "data-destination",
    )
    button_re = re.compile(r"<button\b([^>]*)>", re.I)
    for html_path in NOVA_HTML:
        html = html_path.read_text(encoding="utf-8")
        js_files = list(html_path.parent.glob("*.js"))
        js = "\n".join(item.read_text(encoding="utf-8") for item in js_files)
        for match in button_re.finditer(html):
            attrs = match.group(1)
            if 'type="submit"' in attrs or "type='submit'" in attrs:
                continue
            if any(token in attrs for token in allowed_attr):
                continue
            id_match = re.search(r'id="([^"]+)"', attrs)
            assert id_match, f"unwired button in {html_path.name}: {attrs}"
            button_id = id_match.group(1)
            assert (
                f'$("{button_id}")' in js
                or f"'{button_id}'" in js
                or f'"{button_id}"' in js
            ), f"button #{button_id} has no JS handler in {html_path.parent.name}"


def test_nova_v2_mobile_css_and_viewport() -> None:
    for path in NOVA_HTML:
        html = path.read_text(encoding="utf-8")
        assert "width=device-width" in html, path.name
        assert "viewport-fit=cover" in html, path.name
    for path in NOVA_CSS:
        css = path.read_text(encoding="utf-8")
        assert "@media (max-width: 720px)" in css, path.name


def test_nova_v2_signed_in_surfaces_and_safety() -> None:
    client = _client()
    owner = _login(client)
    staff = _login(client, "staff@amicor.local")

    dashboards = {
        "/api/nova/status": 200,
        "/api/nova/today/dashboard": 200,
        "/api/nova/today/mailbox": 200,
        "/api/nova/today/readiness": 200,
        "/api/nova/workspace/dashboard": 200,
        "/api/nova/communications/dashboard": 200,
        "/api/nova/government/dashboard": 200,
        "/api/nova/business/dashboard": 200,
        "/api/nova/accounting/summary": 200,
        "/api/nova/accounting/aging": 200,
        "/api/nova/accounting/trends": 200,
    }
    for path, expected in dashboards.items():
        response = client.get(path, headers=owner)
        assert response.status_code == expected, f"{path} -> {response.status_code} {response.text[:180]}"
    payments = client.get("/api/nova/payments/readiness", headers=owner)
    assert payments.status_code == 403
    admin = _login(client, "admin@amicor.local")
    assert client.get("/api/nova/payments/readiness", headers=admin).status_code == 200

    asked = client.post("/api/nova/today/ask", headers=owner, json={"question": "What needs attention now?"})
    assert asked.status_code == 200, asked.text
    assert "does not execute" in asked.json()["fact_label"].lower()

    checked = client.post("/api/nova/today/recheck", headers=owner, json={})
    assert checked.status_code == 200, checked.text
    assert checked.json()["mutated_external"] is False

    staff_box = client.get("/api/nova/today/mailbox", headers=staff)
    assert staff_box.status_code == 200
    assert staff_box.json()["items"] == []
    cross = client.post(
        "/api/nova/today/recheck",
        headers=owner,
        json={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403

    for path in ("/api/nova/today/send", "/api/nova/today/file", "/api/nova/today/ledger", "/api/nova/today/call"):
        assert client.post(path, headers=owner).status_code == 403
    blocked = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "communications",
            "source_ref_id": "final-send",
            "title": "Do not send",
            "recommended_action": "send_email",
        },
    )
    assert blocked.status_code == 422
    send = client.post(
        "/api/nova/communications/send",
        headers=owner,
        json={"confirm_send": True, "to": ["a@example.com"], "subject": "no", "body": "no"},
    )
    assert send.status_code == 403
