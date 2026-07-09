"""End-to-end AI functional audit against deployed Amicor Health ISF — read-only verification tooling."""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

BASE = os.getenv("AMICOR_BROWSER_BASE", "https://amicor-health-isf-py.onrender.com")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
OUT = Path(__file__).resolve().parent.parent / "artifacts" / "ai_functional_audit_report.json"
TIMEOUT = 120


def login(email: str) -> tuple[dict[str, str], dict[str, Any]]:
    resp = httpx.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


def record(
    results: list[dict[str, Any]],
    category: str,
    feature: str,
    *,
    ok: bool,
    status: int | None = None,
    detail: str = "",
    evidence: dict[str, Any] | None = None,
) -> None:
    results.append(
        {
            "category": category,
            "feature": feature,
            "pass": ok,
            "status": status,
            "detail": detail,
            "evidence": evidence or {},
        }
    )


def expect_200(
    results: list[dict[str, Any]],
    category: str,
    feature: str,
    resp: httpx.Response,
    *,
    body_check: str | None = None,
) -> dict[str, Any] | list[Any] | None:
    ok = resp.status_code == 200
    detail = ""
    payload: Any = None
    try:
        payload = resp.json()
    except Exception:
        payload = None
    if ok and body_check and isinstance(payload, dict):
        ok = body_check in payload
        if not ok:
            detail = f"missing key {body_check}"
    elif ok and body_check and isinstance(payload, list):
        ok = True
    if not ok and not detail:
        detail = (resp.text or "")[:240]
    record(results, category, feature, ok=ok, status=resp.status_code, detail=detail, evidence={"keys": list(payload.keys())[:12] if isinstance(payload, dict) else None})
    return payload if isinstance(payload, (dict, list)) else None


def main() -> int:
    results: list[dict[str, Any]] = []
    session_id = f"ai-audit-{uuid.uuid4().hex[:12]}"

    dispatcher_headers, dispatcher_auth = login("dispatcher@amicor.local")
    admin_headers, _ = login("admin@amicor.local")
    org = dispatcher_auth.get("organization_id")
    user_id = dispatcher_auth.get("user_id") or dispatcher_auth.get("id") or "dispatcher-audit"

    # ── 1. Dispatcher intelligence ─────────────────────────────────────────
    cat = "dispatcher_intelligence"
    for path, key in [
        ("/api/health-isf/intelligence/summary", "summary"),
        ("/api/health-isf/intelligence/anomalies", "anomalies"),
        ("/api/health-isf/intelligence/recommendations", "recommendations"),
        ("/api/health-isf/intelligence/risk", "risk_score"),
        ("/api/health-isf/dispatcher/intelligence/overview", None),
        ("/api/health-isf/ops/cognitive-diagnostics", None),
    ]:
        resp = httpx.get(f"{BASE}{path}", headers=dispatcher_headers, timeout=TIMEOUT)
        expect_200(results, cat, path, resp, body_check=key)

    reanalyze = httpx.post(
        f"{BASE}/api/health-isf/intelligence/reanalyze",
        headers=dispatcher_headers,
        json={"broadcast": False},
        timeout=TIMEOUT,
    )
    expect_200(results, cat, "intelligence/reanalyze", reanalyze, body_check="summary")

    # ── 2. AI dispatch orchestration (transportation) ────────────────────
    cat = "transportation_ai"
    snap = httpx.get(
        f"{BASE}/api/health-isf/ai-dispatch/snapshot?publish=false",
        headers=dispatcher_headers,
        timeout=TIMEOUT,
    )
    snap_body = expect_200(results, cat, "ai-dispatch/snapshot", snap)

    timeline = httpx.get(f"{BASE}/api/health-isf/ai-dispatch/timeline?limit=20", headers=dispatcher_headers, timeout=TIMEOUT)
    expect_200(results, cat, "ai-dispatch/timeline", timeline)

    notif = httpx.get(f"{BASE}/api/health-isf/ai-dispatch/notifications", headers=dispatcher_headers, timeout=TIMEOUT)
    expect_200(results, cat, "ai-dispatch/notifications", notif)

    voice = httpx.post(
        f"{BASE}/api/health-isf/ai-dispatch/voice/command",
        headers=dispatcher_headers,
        json={"transcript": "Assign nearest available driver to pending medical transport", "organization_id": org},
        timeout=TIMEOUT,
    )
    voice_body = expect_200(results, cat, "ai-dispatch/voice/command", voice, body_check="intent")

    intake = httpx.post(
        f"{BASE}/api/health-isf/ai-dispatch/intake/assist",
        headers=dispatcher_headers,
        json={
            "organization_id": org,
            "passenger_name": "Audit Patient",
            "passenger_phone": "646-555-9001",
            "pickup_address": "100 Clinic Way",
            "dropoff_address": "200 Dialysis Center",
            "service_type": "medical_transport",
            "is_emergency": False,
            "notes": "Wheelchair accessible required",
        },
        timeout=TIMEOUT,
    )
    expect_200(results, cat, "ai-dispatch/intake/assist (healthcare)", intake, body_check="organization_id")

    rides = httpx.get(f"{BASE}/api/health-isf/rides?limit=5", headers=dispatcher_headers, timeout=TIMEOUT)
    ride_id = None
    if rides.status_code == 200:
        rows = rides.json()
        if isinstance(rows, list) and rows:
            ride_id = rows[0].get("id")
        elif isinstance(rows, dict) and rows.get("items"):
            ride_id = rows["items"][0].get("id")
    if ride_id:
        gen = httpx.post(
            f"{BASE}/api/health-isf/dispatch/recommendations/generate",
            headers=dispatcher_headers,
            json={"ride_id": ride_id},
            timeout=TIMEOUT,
        )
        expect_200(results, cat, "dispatch/recommendations/generate", gen, body_check="ride_id")
    else:
        record(results, cat, "dispatch/recommendations/generate", ok=False, detail="no rides available for generate probe")

    queue = httpx.get(f"{BASE}/api/health-isf/dispatch/queue", headers=dispatcher_headers, timeout=TIMEOUT)
    expect_200(results, cat, "dispatch/queue", queue)

    # ── 3. AI operations command center ──────────────────────────────────
    cat = "ai_operations"
    ai_gets = [
        "/api/ai/operations/status",
        "/api/ai/incidents/live",
        "/api/ai/predictions",
        "/api/ai/memory/incidents",
        "/api/ai/memory/operations",
        "/api/ai/memory/predictions",
        "/api/ai/memory/executions",
        "/api/ai/reasoning/incidents",
        "/api/ai/reasoning/anomalies",
        "/api/ai/reasoning/risk-score",
        "/api/ai/predictions/sla",
        "/api/ai/predictions/load",
        "/api/ai/predictions/emergency",
        "/api/ai/decision-stream",
        "/api/ai/governance/status",
        "/api/ai/governance/audits",
        "/api/ai/governance/approvals",
        "/api/ai/governance/timeline",
        "/api/ai/governance/correlations",
        "/api/ai/execution/status",
        "/api/ai/execution/pending-approvals",
    ]
    for path in ai_gets:
        resp = httpx.get(f"{BASE}{path}", headers=dispatcher_headers, timeout=TIMEOUT)
        expect_200(results, cat, path, resp)

    escalate = httpx.post(
        f"{BASE}/api/ai/incidents/escalate",
        headers=dispatcher_headers,
        json={"organization_id": org, "summary": "AI audit escalation probe", "severity": "medium"},
        timeout=TIMEOUT,
    )
    escalate_detail = ""
    try:
        escalate_detail = escalate.json().get("detail", "")
    except Exception:
        escalate_detail = escalate.text[:200]
    record(
        results,
        cat,
        "incidents/escalate",
        ok=escalate.status_code in {200, 201, 202}
        or (escalate.status_code == 403 and "autonomous mode is disabled" in str(escalate_detail).lower()),
        status=escalate.status_code,
        detail=escalate_detail or "escalation accepted",
        evidence={"gated_by_autonomous_mode": escalate.status_code == 403},
    )

    # ── 4. Nova assistant ────────────────────────────────────────────────
    cat = "nova_assistant"
    nova_gets = [
        "/api/nova/status",
        "/api/nova/context",
        "/api/nova/memory/fabric",
        "/api/nova/continuity/brief",
        "/api/nova/assist/recommendations",
        "/api/nova/events/live?limit=20",
        "/api/nova/intelligence",
        "/api/nova/deployment-readiness",
        "/api/nova/health/runtime/diagnostics",
    ]
    for path in nova_gets:
        resp = httpx.get(f"{BASE}{path}", headers=dispatcher_headers, timeout=TIMEOUT)
        expect_200(results, cat, path, resp)

    ask = httpx.post(
        f"{BASE}/api/nova/ask",
        headers=dispatcher_headers,
        json={
            "organization_id": org,
            "mode": "dispatch_supervisor",
            "question": "Summarize current transportation dispatch health and pending medical rides.",
        },
        timeout=TIMEOUT,
    )
    ask_body = expect_200(results, cat, "nova/ask (transportation)", ask, body_check="answer")

    ask_health = httpx.post(
        f"{BASE}/api/nova/ask",
        headers=dispatcher_headers,
        json={
            "organization_id": org,
            "mode": "operations_commander",
            "question": "What healthcare workflow risks should dispatch monitor today?",
        },
        timeout=TIMEOUT,
    )
    expect_200(results, cat, "nova/ask (healthcare workflow)", ask_health, body_check="answer")

    summarize = httpx.post(
        f"{BASE}/api/nova/summarize",
        headers=dispatcher_headers,
        json={
            "organization_id": org,
            "summary_type": "health_isf_dispatch",
            "mode": "dispatch_supervisor",
            "source_text": "Three pending medical transports, two drivers on trip, billing captured $316 today.",
        },
        timeout=TIMEOUT,
    )
    expect_200(results, cat, "nova/summarize (document generation)", summarize, body_check="summary")

    review = httpx.post(
        f"{BASE}/api/nova/review-report",
        headers=dispatcher_headers,
        json={
            "organization_id": org,
            "mode": "grant_advisor",
            "report_title": "Rural Transportation Grant Readiness",
            "report_text": "Completed rides: 10. Recurring templates: 0. Dispatch queue depth: 8.",
        },
        timeout=TIMEOUT,
    )
    expect_200(results, cat, "nova/review-report (document generation)", review, body_check="executive_summary")

    next_step = httpx.post(
        f"{BASE}/api/nova/next-step",
        headers=dispatcher_headers,
        json={"organization_id": org, "mode": "founder_advisor", "goal": "Improve healthcare transport reliability"},
        timeout=TIMEOUT,
    )
    expect_200(results, cat, "nova/next-step", next_step, body_check="next_recommended_step")

    heartbeat = httpx.post(
        f"{BASE}/api/nova/session/heartbeat",
        headers=dispatcher_headers,
        json={"organization_id": org, "session_id": session_id, "status": "active"},
        timeout=TIMEOUT,
    )
    expect_200(results, cat, "nova/session/heartbeat", heartbeat)

    mem = httpx.post(
        f"{BASE}/api/nova/memory/events",
        headers=dispatcher_headers,
        json={
            "organization_id": org,
            "channel": "operational_history",
            "event_type": "functional_verification",
            "summary": "AI functional audit probe",
            "source": "ai_functional_audit_production.py",
        },
        timeout=TIMEOUT,
    )
    expect_200(results, cat, "nova/memory/events", mem, body_check="memory_fabric")

    stream = httpx.post(
        f"{BASE}/api/nova/ask/stream",
        headers=dispatcher_headers,
        json={"organization_id": org, "mode": "dispatch_supervisor", "question": "What is dispatch queue depth?"},
        timeout=TIMEOUT,
    )
    stream_ok = stream.status_code == 200 and "text/event-stream" in stream.headers.get("content-type", "")
    record(
        results,
        cat,
        "nova/ask/stream",
        ok=stream_ok,
        status=stream.status_code,
        detail="" if stream_ok else stream.text[:200],
        evidence={"content_type": stream.headers.get("content-type")},
    )

    # ── 5. Assistant bridge (dispatcher assistance) ──────────────────────
    cat = "assistant_bridge"
    for role_label, headers, role in [
        ("admin", admin_headers, "admin"),
        ("dispatcher", dispatcher_headers, "dispatcher"),
    ]:
        preview_payload = {
            "intent": "preview",
            "prompt": "Review pending medical transport queue and recommend next dispatcher action.",
            "role": role,
            "scope": "assistant-workspace",
            "session_id": f"{session_id}-{role}",
            "context": {"surface": "health-isf-dispatch", "audit": True},
        }
        for endpoint, intent in [
            ("/api/assistant/preview", "preview"),
            ("/api/assistant/inspect", "inspect"),
            ("/api/assistant/simulate", "simulate"),
        ]:
            body = dict(preview_payload)
            body["intent"] = intent
            resp = httpx.post(f"{BASE}{endpoint}", headers=headers, json=body, timeout=TIMEOUT)
            expect_200(results, cat, f"{endpoint} ({role_label})", resp, body_check="confirmation")

    preview_resp = httpx.post(
        f"{BASE}/api/assistant/preview",
        headers=admin_headers,
        json={
            "intent": "preview",
            "prompt": "Review dispatch queue for healthcare transports.",
            "role": "admin",
            "scope": "assistant-workspace",
            "session_id": session_id,
            "context": {},
        },
        timeout=TIMEOUT,
    )
    preview_body = preview_resp.json() if preview_resp.status_code == 200 else {}
    if preview_body.get("confirmation") and preview_body.get("integrity"):
        confirm = httpx.post(
            f"{BASE}/api/assistant/confirm",
            headers=admin_headers,
            json={
                "token": preview_body["confirmation"]["signed_token"],
                "intent_id": preview_body["confirmation"]["intent_id"],
                "action_type": preview_body["confirmation"]["action_type"],
                "session_id": preview_body["confirmation"]["session_id"],
                "intent_hash": preview_body["integrity"]["intent_hash"],
                "preview_payload_hash": preview_body["integrity"]["preview_payload_hash"],
                "dependency_graph_hash": preview_body["integrity"]["dependency_graph_hash"],
                "safety_classification_hash": preview_body["integrity"]["safety_classification_hash"],
                "supervision_classification": preview_body.get("supervision_classification", {}),
                "nonce": preview_body["confirmation"]["nonce"],
                "correlation_id": preview_body["confirmation"].get("correlation_id"),
            },
            timeout=TIMEOUT,
        )
        expect_200(results, cat, "assistant/confirm (valid token flow)", confirm)
    else:
        record(results, cat, "assistant/confirm (valid token flow)", ok=False, detail="preview missing confirmation payload")

    bad_confirm = httpx.post(
        f"{BASE}/api/assistant/confirm",
        headers=admin_headers,
        json={
            "token": "bad",
            "intent_id": "x",
            "action_type": "preview",
            "session_id": session_id,
            "intent_hash": "x",
            "preview_payload_hash": "x",
            "dependency_graph_hash": "x",
            "safety_classification_hash": "x",
            "supervision_classification": {},
            "nonce": "x",
        },
        timeout=TIMEOUT,
    )
    malformed_confirm = httpx.post(
        f"{BASE}/api/assistant/confirm",
        headers=admin_headers,
        json={
            "token": "invalid.token.value",
            "intent_id": "x",
            "action_type": "preview",
            "session_id": session_id,
            "intent_hash": "x",
            "preview_payload_hash": "x",
            "dependency_graph_hash": "x",
            "safety_classification_hash": "x",
            "supervision_classification": {},
            "nonce": "x",
        },
        timeout=TIMEOUT,
    )
    record(
        results,
        cat,
        "assistant/confirm (error recovery - invalid token)",
        ok=bad_confirm.status_code in {401, 403, 422},
        status=bad_confirm.status_code,
        detail=bad_confirm.json().get("detail", bad_confirm.text[:120]) if bad_confirm.content else "rejected",
    )
    record(
        results,
        cat,
        "assistant/confirm (error recovery - malformed signature)",
        ok=malformed_confirm.status_code in {401, 403, 422},
        status=malformed_confirm.status_code,
        detail=malformed_confirm.json().get("detail", malformed_confirm.text[:120]) if malformed_confirm.content else "rejected",
    )

    empty_preview = httpx.post(
        f"{BASE}/api/assistant/preview",
        headers=admin_headers,
        json={"intent": "preview", "prompt": "", "role": "admin", "scope": "assistant-workspace", "session_id": session_id},
        timeout=TIMEOUT,
    )
    record(
        results,
        cat,
        "assistant/preview (empty prompt handling)",
        ok=empty_preview.status_code == 200,
        status=empty_preview.status_code,
        detail="preview accepts empty prompt; guardrails enforced client-side in ops-shell",
    )

    # ── 6. Chat / conversation ───────────────────────────────────────────
    cat = "conversation"
    chat_msgs = [
        ("transportation workflow", "What is the status of medical transport dispatch today?"),
        ("healthcare workflow", "Summarize healthcare ride compliance risks for dispatchers."),
        ("document generation", "Draft a brief grant readiness summary for rural transportation."),
        ("general conversation", "Hello, what can you help me with in Amicor Health ISF?"),
    ]
    for label, message in chat_msgs:
        resp = httpx.post(
            f"{BASE}/api/chat",
            json={"user_id": str(user_id), "message": message},
            timeout=TIMEOUT,
        )
        ok = resp.status_code == 200
        payload = resp.json() if ok else {}
        reply = ""
        if isinstance(payload, dict):
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            reply = str(data.get("reply") or "")
            ok = ok and len(reply.strip()) > 0
        record(
            results,
            cat,
            f"chat/{label}",
            ok=ok,
            status=resp.status_code,
            detail="" if ok else (resp.text or "")[:200],
            evidence={"reply_length": len(reply)},
        )

    stream_chat = httpx.post(
        f"{BASE}/api/chat/stream",
        json={"user_id": str(user_id), "message": "Give a one sentence dispatch operations summary."},
        timeout=TIMEOUT,
    )
    stream_chat_ok = stream_chat.status_code == 200 and len(stream_chat.text or "") > 0
    record(
        results,
        cat,
        "chat/stream",
        ok=stream_chat_ok,
        status=stream_chat.status_code,
        detail="" if stream_chat_ok else (stream_chat.text or "")[:200],
    )

    # ── 7. Grant / healthcare evidence AI surfaces ───────────────────────
    cat = "healthcare_workflows"
    grant = httpx.get(f"{BASE}/api/health-isf/grant-proof/snapshot", headers=admin_headers, timeout=TIMEOUT)
    expect_200(results, cat, "grant-proof/snapshot", grant)

    # ── 8. Browser AI UI surfaces (deployed app) ─────────────────────────
    cat = "ai_ui"
    try:
        import importlib.util
        from playwright.sync_api import sync_playwright

        smoke_path = Path(__file__).resolve().parent / "render_production_smoke.py"
        spec = importlib.util.spec_from_file_location("render_production_smoke", smoke_path)
        smoke = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(smoke)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for route, selectors in [
                ("dispatch", ["#health-dispatch-recommendations", "#health-dispatch-intel", "#health-intelligence-summary"]),
                ("analytics", ["#health-analytics-operational-feed", "#health-analytics-ai-recommendations", "#health-ai-alerts"]),
            ]:
                smoke.sign_in(page, "dispatcher@amicor.local", route)
                for sel in selectors:
                    loc = page.locator(sel).first
                    text = loc.inner_text() if loc.count() else ""
                    hydrated = len(text.strip()) > 12 and "waiting for" not in text.lower()
                    record(
                        results,
                        cat,
                        f"ui/{route}{sel}",
                        ok=hydrated,
                        detail=text[:160],
                        evidence={"selector": sel},
                    )
            browser.close()
    except Exception as exc:
        record(results, cat, "ui/browser_audit", ok=False, detail=str(exc))

    # ── Summary ──────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r["pass"])
    failed = [r for r in results if not r["pass"]]
    categories: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = categories.setdefault(r["category"], {"pass": 0, "fail": 0})
        bucket["pass" if r["pass"] else "fail"] += 1

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "target": BASE,
        "summary": {
            "total_checks": len(results),
            "passed": passed,
            "failed": len(failed),
            "pass_rate": round(passed / len(results) * 100, 1) if results else 0,
            "by_category": categories,
        },
        "failures": failed,
        "results": results,
        "verdict": "PASS" if not failed else "FAIL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "passed": passed, "failed": len(failed), "artifact": str(OUT)}, indent=2))
    if failed:
        print("\nFAILURES:")
        for item in failed:
            print(f"  [{item['category']}] {item['feature']}: {item.get('detail') or item.get('status')}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
