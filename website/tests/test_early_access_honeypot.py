"""Regression tests for the Early Access honeypot rename.

Website-only. Does not call production, KV, Stripe, or Nova.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "early-access" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "assets" / "js" / "site.js").read_text(encoding="utf-8")
CONFIG = (ROOT / "assets" / "js" / "site-config.js").read_text(encoding="utf-8")
LEADS = (ROOT / "functions" / "api" / "leads.js").read_text(encoding="utf-8")
CSS = (ROOT / "assets" / "css" / "site.css").read_text(encoding="utf-8")

HONEYPOT = "middle_name_confirm"
FORBIDDEN_TOKENS = ("website", "company", "url", "homepage", "site")
VISIBLE_FIELDS = ("name", "company", "email", "phone", "industry", "companySize", "product", "message")
LEGITIMATE_PAYLOAD_FIELDS = (
    "receivedAt",
    "name",
    "company",
    "email",
    "phone",
    "industry",
    "companySize",
    "product",
    "message",
    "consent",
    "source",
)


def _form_html() -> str:
    match = re.search(r'<form class="panel" data-early-access-form[^>]*>(.*?)</form>', HTML, re.S)
    assert match, "Early Access form markup is missing"
    return match.group(1)


def honeypot_blocks(form_data: dict[str, str]) -> bool:
    return bool(str(form_data.get(HONEYPOT) or "").strip())


def valid_visible_form(*, honeypot: str = "") -> dict[str, str]:
    return {
        "name": "Jordan Hale",
        "company": "North Star Transit",
        "email": "jordan@northstar.example",
        "phone": "555-0100",
        "industry": "Healthcare operations",
        "companySize": "11-50",
        "product": "Autonomous Operations Agent",
        "message": "I would like a product demo.",
        "consent": "yes",
        HONEYPOT: honeypot,
    }


def chrome_like_visible_autofill() -> dict[str, str]:
    """Autofill maps only ordinary visible autocomplete names, not the honeypot."""
    return {
        "name": "Jordan Hale",
        "company": "North Star Transit",
        "email": "jordan@northstar.example",
        "phone": "555-0100",
        "industry": "",
        "companySize": "",
        "product": "Autonomous Operations Agent",
        "message": "",
        "consent": "",
    }


def would_reach_lead_submit(form_data: dict[str, str]) -> bool:
    if honeypot_blocks(form_data):
        return False
    for field in ("name", "company", "email", "industry", "companySize", "product", "message"):
        if not str(form_data.get(field) or "").strip():
            return False
    if form_data.get("consent") not in {"yes", "true", True}:
        return False
    return True


def build_payload(form_data: dict[str, str]) -> dict[str, object]:
    return {
        "receivedAt": "2026-09-15T03:00:00.000Z",
        "name": form_data["name"].strip(),
        "company": form_data["company"].strip(),
        "email": form_data["email"].strip(),
        "phone": str(form_data.get("phone") or "").strip(),
        "industry": form_data["industry"].strip(),
        "companySize": form_data["companySize"],
        "product": form_data["product"],
        "message": form_data["message"].strip(),
        "consent": True,
        "source": "amicor-public-website-w8",
    }


def test_honeypot_renamed_and_hidden() -> None:
    form = _form_html()
    names = re.findall(r'name="([^"]+)"', form)
    assert HONEYPOT in names
    assert "company_website" not in names
    for token in FORBIDDEN_TOKENS:
        assert token not in HONEYPOT
    hp_markup = re.search(
        r'<div class="hp"[^>]*>\s*<input name="middle_name_confirm"[^>]*>\s*</div>',
        form,
        re.S,
    )
    assert hp_markup, "Honeypot must stay inside the hidden .hp wrapper"
    assert "Company website" not in form
    assert 'autocomplete="off"' in hp_markup.group(0)
    assert "aria-hidden" in hp_markup.group(0)
    assert "tabindex=\"-1\"" in hp_markup.group(0)
    assert ".hp { position: absolute; left: -9999px; height: 0; overflow: hidden; }" in CSS


def test_site_js_uses_new_honeypot_and_preserves_submit_path() -> None:
    assert "data.middle_name_confirm" in JS
    assert "data.company_website" not in JS
    assert 'formEndpoint: "/api/leads"' in CONFIG
    assert "fetch(endpoint" in JS
    assert 'method: "POST"' in JS
    assert 'headers: { "Content-Type": "application/json" }' in JS
    assert "JSON.stringify(payload)" in JS
    assert "Thank you. Your request was sent to AMICOR." in JS
    assert "Request could not be sent." in JS
    for field in VISIBLE_FIELDS:
        assert f"{field}:" in JS or f"data.{field}" in JS
    assert "consent: true" in JS
    assert 'source: "amicor-public-website-w8"' in JS


def test_empty_honeypot_reaches_lead_submit_path() -> None:
    form_data = valid_visible_form(honeypot="")
    assert would_reach_lead_submit(form_data) is True
    payload = build_payload(form_data)
    assert HONEYPOT not in payload
    assert set(payload) == set(LEGITIMATE_PAYLOAD_FIELDS)
    assert payload["product"] == "Autonomous Operations Agent"
    assert payload["consent"] is True


def test_visible_autofill_does_not_populate_honeypot() -> None:
    autofilled = chrome_like_visible_autofill()
    assert HONEYPOT not in autofilled
    merged = {**autofilled, HONEYPOT: ""}
    assert honeypot_blocks(merged) is False
    completed = valid_visible_form(honeypot="")
    for field in ("name", "company", "email", "phone"):
        completed[field] = autofilled[field]
    assert would_reach_lead_submit(completed) is True


def test_nonempty_honeypot_still_blocks() -> None:
    blocked = valid_visible_form(honeypot="https://autofill.example")
    assert honeypot_blocks(blocked) is True
    assert would_reach_lead_submit(blocked) is False
    assert 'errorBox.textContent = "Request could not be sent."' in JS


def test_leads_function_and_kv_path_unchanged() -> None:
    assert "plain(raw.middle_name_confirm, 200)" in LEADS
    assert "env.AMICOR_LEADS" in LEADS
    assert 'source: "amicor-public-website-w8"' in LEADS
    assert "store.put(`lead:${payload.receivedAt}:${id}`" in LEADS
    assert 'return json(202, { ok: true, stored, notified });' in LEADS


def main() -> None:
    tests = [
        test_honeypot_renamed_and_hidden,
        test_site_js_uses_new_honeypot_and_preserves_submit_path,
        test_empty_honeypot_reaches_lead_submit_path,
        test_visible_autofill_does_not_populate_honeypot,
        test_nonempty_honeypot_still_blocks,
        test_leads_function_and_kv_path_unchanged,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"TESTS_PASSED={len(tests)}")


if __name__ == "__main__":
    main()
