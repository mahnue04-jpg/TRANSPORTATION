"""Resolve production dispatcher/rider JWTs for QA automation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

REPO = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]

def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    candidates = (
        REPO / ".env",
        BACKEND / ".env",
        REPO / ".runtime" / "production.env",
        REPO / ".runtime" / "production_credentials.env",
        Path.home() / ".amicor" / "production.env",
    )
    extra = os.getenv("AMICOR_PRODUCTION_ENV_FILE", "").strip()
    if extra:
        candidates = (Path(extra),) + candidates
    for env_path in candidates:
        if env_path.is_file():
            load_dotenv(env_path, override=True)


_load_env_files()

BASE = os.getenv("AMICOR_RENDER_BASE", "https://amicor-health-isf-py.onrender.com").rstrip("/")
OPERATOR_EMAIL = os.getenv("AMICOR_OPERATOR_EMAIL", "mahnue04@gmail.com").strip().lower()
DISPATCHER_EMAIL = os.getenv("AMICOR_DISPATCHER_EMAIL", "dispatcher@amicor.local").strip().lower()
RIDER_EMAIL = os.getenv("AMICOR_RIDER_EMAIL", "rider@amicor.local").strip().lower()


def _password_candidates() -> list[str]:
    candidates: list[str] = []
    for key in (
        "AMICOR_SEED_PASSWORD",
        "AMICOR_DEPLOYMENT_SYNC_KEY",
        "AMICOR_OPERATOR_PASSWORD",
        "AMICOR_PRODUCTION_PASSWORD",
    ):
        value = os.getenv(key, "").strip()
        if value and value not in candidates:
            candidates.append(value)
    default = "Amicor123!"
    if default not in candidates:
        candidates.append(default)
    return candidates


def _login(email: str, password: str) -> tuple[int, dict[str, Any]]:
    resp = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": password},
        timeout=60,
    )
    body: dict[str, Any] = {}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"detail": resp.text[:300]}
    return resp.status_code, body


def _sync_seed(sync_key: str) -> tuple[int, dict[str, Any]]:
    resp = requests.post(
        f"{BASE}/api/auth/deployment/sync-seed-users",
        headers={"X-Amicor-Deployment-Key": sync_key},
        timeout=120,
    )
    body: dict[str, Any] = {}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"detail": resp.text[:300]}
    return resp.status_code, body


def _operator_token(sync_key: str, role: str = "dispatcher") -> tuple[int, dict[str, Any]]:
    resp = requests.post(
        f"{BASE}/api/auth/deployment/operator-workspace-token",
        headers={"X-Amicor-Deployment-Key": sync_key, "Content-Type": "application/json"},
        json={"role": role},
        timeout=60,
    )
    body: dict[str, Any] = {}
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"detail": resp.text[:300]}
    return resp.status_code, body


def _ensure_dispatcher_role(token: str) -> tuple[str, dict[str, Any]]:
    session = requests.get(
        f"{BASE}/api/auth/session",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    session_body = session.json() if session.ok else {}
    role = str(session_body.get("role") or "")
    if role == "dispatcher":
        return token, session_body
    refresh = str(session_body.get("refresh_token") or "")
    if not refresh:
        return token, session_body
    switch = requests.post(
        f"{BASE}/api/auth/switch-role",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"role": "dispatcher"},
        timeout=30,
    )
    if switch.status_code != 200:
        return token, session_body
    switch_body = switch.json()
    return str(switch_body.get("access_token") or token), switch_body


def resolve_production_tokens() -> dict[str, Any]:
    """Return dispatcher/rider tokens plus auth audit trail (no secrets)."""
    audit: list[dict[str, Any]] = []
    dispatcher_token = os.getenv("AMICOR_DISPATCHER_ACCESS_TOKEN", "").strip()
    rider_token = os.getenv("AMICOR_RIDER_ACCESS_TOKEN", "").strip()
    shared_jwt = os.getenv("AMICOR_PRODUCTION_JWT", "").strip()

    if shared_jwt:
        dispatcher_token = dispatcher_token or shared_jwt
        rider_token = rider_token or shared_jwt
        audit.append({"method": "env_jwt", "ok": True})

    if dispatcher_token and rider_token:
        return {
            "ok": True,
            "dispatcher_token": dispatcher_token,
            "rider_token": rider_token,
            "dispatcher_email": DISPATCHER_EMAIL,
            "auth_method": "env_token",
            "audit": audit,
        }

    passwords = _password_candidates()
    sync_keys = [p for p in passwords if p]

    emails = [OPERATOR_EMAIL, DISPATCHER_EMAIL, RIDER_EMAIL]
    for password in passwords:
        for email in emails:
            status, body = _login(email, password)
            audit.append({"method": "password_login", "email": email, "status": status})
            if status != 200:
                continue
            token = str(body.get("access_token") or "")
            if not token:
                continue
            if email == RIDER_EMAIL:
                rider_token = token
            else:
                dispatcher_token, switch_body = _ensure_dispatcher_role(token)
                audit.append({"method": "dispatcher_role", "role": switch_body.get("role"), "status": 200})
            if dispatcher_token and rider_token:
                return {
                    "ok": True,
                    "dispatcher_token": dispatcher_token,
                    "rider_token": rider_token,
                    "dispatcher_email": email if email != RIDER_EMAIL else DISPATCHER_EMAIL,
                    "auth_method": "password_login",
                    "audit": audit,
                }

    for sync_key in sync_keys:
        sync_status, _ = _sync_seed(sync_key)
        audit.append({"method": "sync_seed_users", "status": sync_status})
        if sync_status == 200:
            for email in (DISPATCHER_EMAIL, OPERATOR_EMAIL, RIDER_EMAIL):
                status, body = _login(email, sync_key)
                audit.append({"method": "post_sync_login", "email": email, "status": status})
                if status != 200:
                    continue
                token = str(body.get("access_token") or "")
                if email == RIDER_EMAIL:
                    rider_token = token
                else:
                    dispatcher_token, _ = _ensure_dispatcher_role(token)
                if dispatcher_token and rider_token:
                    return {
                        "ok": True,
                        "dispatcher_token": dispatcher_token,
                        "rider_token": rider_token,
                        "dispatcher_email": email if email != RIDER_EMAIL else DISPATCHER_EMAIL,
                        "auth_method": "sync_seed_users",
                        "audit": audit,
                    }

    for sync_key in sync_keys:
        status, body = _operator_token(sync_key, "dispatcher")
        audit.append({"method": "operator_workspace_token", "status": status})
        if status != 200:
            continue
        dispatcher_token = str(body.get("access_token") or "")
        for password in passwords:
            rider_status, rider_body = _login(RIDER_EMAIL, password)
            audit.append({"method": "rider_login_after_operator_token", "status": rider_status})
            if rider_status == 200:
                rider_token = str(rider_body.get("access_token") or "")
                break
        if dispatcher_token and rider_token:
            return {
                "ok": True,
                "dispatcher_token": dispatcher_token,
                "rider_token": rider_token,
                "dispatcher_email": OPERATOR_EMAIL,
                "auth_method": "operator_workspace_token",
                "audit": audit,
            }

    return {
        "ok": False,
        "dispatcher_token": "",
        "rider_token": "",
        "dispatcher_email": DISPATCHER_EMAIL,
        "auth_method": "",
        "audit": audit,
        "error": (
            "Production auth failed. Set AMICOR_SEED_PASSWORD and AMICOR_DEPLOYMENT_SYNC_KEY "
            "to the Render runtime values, or set AMICOR_DISPATCHER_ACCESS_TOKEN / AMICOR_RIDER_ACCESS_TOKEN."
        ),
    }
