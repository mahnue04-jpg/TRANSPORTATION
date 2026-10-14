"""Nova Snap preview: messaging, direct calls, and private camera drafts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, UserContext, ensure_auth_schema, seed_default_users
from app.core.nova.snap import policy, service
from app.core.nova.snap.models import SnapCallParticipant, SnapMember, SnapMessage
from app.main import app

JPEG = b"\xff\xd8\xff" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def user(uid="owner", org="org", role="dispatcher"):
    return UserContext(user_id=uid, email=f"{uid}@example.com", role=role, organization_id=org)


@pytest.fixture(autouse=True)
def _limits():
    service.reset_limits()
    yield
    service.reset_limits()


def test_status_is_a_preview_without_turn_or_secrets(monkeypatch):
    monkeypatch.delenv("SNAP_TURN_URLS", raising=False)
    monkeypatch.delenv("SNAP_TURN_USERNAME", raising=False)
    monkeypatch.delenv("SNAP_TURN_CREDENTIAL", raising=False)
    status = policy.public_status()
    assert status["product"] == "Nova Snap"
    assert status["production_ready"] is False
    assert status["turn_configured"] is False
    assert status["quality_guarantee"] is False
    assert "AMICOR Synapse meetings" in status["distinct_from"]
    assert "Nova Casting auditions" in status["distinct_from"]
    assert "credential" not in status
    assert "ice_servers" not in status
    assert status["calling_blocker"]


def test_contact_requires_acceptance_before_direct_or_group(db):
    owner, peer, stranger = user("owner"), user("peer"), user("stranger")
    pending = service.request_contact(db, owner, peer.user_id)
    assert pending["status"] == "pending"
    with pytest.raises(HTTPException) as err:
        service.create_direct(db, owner, peer.user_id)
    assert err.value.status_code == 403
    with pytest.raises(HTTPException):
        service.respond_contact(db, owner, pending["contact_id"], True)
    accepted = service.respond_contact(db, peer, pending["contact_id"], True)
    assert accepted["status"] == "accepted"
    direct = service.create_direct(db, owner, peer.user_id)
    again = service.create_direct(db, peer, owner.user_id)
    assert again["conversation_id"] == direct["conversation_id"]
    with pytest.raises(HTTPException) as err:
        service.create_group(db, owner, "Crew", [stranger.user_id])
    assert err.value.status_code == 403
    service.request_contact(db, owner, stranger.user_id)
    service.respond_contact(db, stranger, service.list_contacts(db, stranger)[0]["contact_id"], True)
    group = service.create_group(db, owner, "Crew", [peer.user_id, stranger.user_id])
    assert group["kind"] == "group"
    assert len(group["members"]) == 3


def test_messages_retry_unread_read_and_hide_unsafe_links(db):
    owner, peer = user("owner"), user("peer")
    contact = service.request_contact(db, owner, peer.user_id)
    service.respond_contact(db, peer, contact["contact_id"], True)
    conversation = service.create_direct(db, owner, peer.user_id)["conversation_id"]
    with pytest.raises(HTTPException) as err:
        service.post_message(db, owner, conversation, "go javascript:alert(1)", "client-unsafe-01")
    assert err.value.status_code == 400
    assert service.list_messages(db, peer, conversation) == []
    sent = service.post_message(db, owner, conversation, "Hello https://example.com", "client-hello-01")
    assert sent["untrusted_links"] is True
    assert sent["delivery"] == "stored"
    duplicate = service.post_message(db, owner, conversation, "Hello https://example.com", "client-hello-01")
    assert duplicate["duplicate"] is True
    assert duplicate["message_id"] == sent["message_id"]
    assert len(service.list_messages(db, owner, conversation)) == 1
    inbox = service.list_conversations(db, peer)
    assert inbox[0]["unread"] == 1
    delivered = service.list_messages(db, peer, conversation)
    assert delivered[0]["delivery"] == "delivered"
    service.mark_read(db, peer, conversation, sent["message_id"])
    assert service.list_messages(db, owner, conversation)[0]["delivery"] == "read"
    assert service.list_conversations(db, peer)[0]["unread"] == 0
    with pytest.raises(HTTPException) as err:
        service.list_messages(db, user("outsider"), conversation)
    assert err.value.status_code == 404
    with pytest.raises(HTTPException) as err:
        service.list_messages(db, user("owner", "other-org"), conversation)
    assert err.value.status_code == 404


def test_block_report_delete_retention_and_rate_limit(db):
    owner, peer = user("owner"), user("peer")
    contact = service.request_contact(db, owner, peer.user_id)
    service.respond_contact(db, peer, contact["contact_id"], True)
    conversation = service.create_direct(db, owner, peer.user_id)["conversation_id"]
    sent = service.post_message(db, owner, conversation, "Keep this private", "client-keep-0001")
    removed = service.delete_message(db, owner, sent["message_id"])
    assert removed["removed"] is True
    assert removed["body"] == ""
    assert service.list_messages(db, peer, conversation)[0]["body"] == ""
    with pytest.raises(HTTPException):
        service.delete_message(db, peer, sent["message_id"])
    report = service.report_message(db, peer, target_user_id=owner.user_id, reason="Unwanted message", message_id=sent["message_id"])
    assert report["moderator_delivery"] is False
    assert service.list_reports(db, owner) == []
    assert service.list_reports(db, peer)[0]["report_id"] == report["report_id"]
    service.block_user(db, peer, owner.user_id)
    with pytest.raises(HTTPException) as err:
        service.post_message(db, owner, conversation, "Still there?", "client-blocked-1")
    assert err.value.status_code == 404
    with pytest.raises(HTTPException):
        service.list_messages(db, owner, conversation)
    service.unblock_user(db, peer, owner.user_id)
    service.reset_limits()
    for index in range(30):
        service.post_message(db, owner, conversation, f"n{index}", f"client-rate-{index:02d}")
    with pytest.raises(HTTPException) as err:
        service.post_message(db, owner, conversation, "too many", "client-rate-99")
    assert err.value.status_code == 429
    old = db.query(SnapMessage).filter_by(client_message_id="client-rate-00").one()
    old.created_at = datetime.now(timezone.utc) - timedelta(days=31)
    for member in db.query(SnapMember).filter_by(conversation_id=conversation).all():
        member.joined_at = datetime.now(timezone.utc) - timedelta(days=40)
    db.commit()
    listed = service.list_messages(db, peer, conversation)
    expired = [row for row in listed if row["message_id"] == old.message_id][0]
    assert expired["removed"] is True


def test_call_accept_signal_reconnect_and_network_timeout(db):
    owner, peer = user("owner"), user("peer")
    contact = service.request_contact(db, owner, peer.user_id)
    service.respond_contact(db, peer, contact["contact_id"], True)
    conversation = service.create_direct(db, owner, peer.user_id)["conversation_id"]
    call = service.start_call(db, owner, conversation, "video")
    assert call["state"] == "ringing"
    assert call["turn_configured"] is False
    assert call["quality_guarantee"] is False
    assert service.list_incoming(db, peer)[0]["call_id"] == call["call_id"]
    with pytest.raises(HTTPException) as err:
        service.post_signal(db, peer, call["call_id"], kind="answer", payload="v=0", client_signal_id="signal-early-1")
    assert err.value.status_code == 409
    offered = service.post_signal(db, owner, call["call_id"], kind="offer", payload="v=0", client_signal_id="signal-offer-1")
    assert offered["duplicate"] is False
    assert service.post_signal(db, owner, call["call_id"], kind="offer", payload="v=0", client_signal_id="signal-offer-1")["duplicate"] is True
    assert service.list_signals(db, owner, call["call_id"]) == []
    accepted = service.accept_call(db, peer, call["call_id"])
    assert accepted["state"] == "active"
    assert service.list_signals(db, peer, call["call_id"])[0]["kind"] == "offer"
    service.post_signal(db, peer, call["call_id"], kind="answer", payload="v=0", client_signal_id="signal-answer-1")
    service.post_signal(db, peer, call["call_id"], kind="quality", payload="poor", client_signal_id="signal-quality-1")
    assert service.get_call(db, peer, call["call_id"])["quality"] == "poor"
    assert service.reconnect_call(db, peer, call["call_id"])["my_state"] == "reconnecting"
    for person in db.query(SnapCallParticipant).filter_by(call_id=call["call_id"]).all():
        person.last_seen = datetime.now(timezone.utc) - timedelta(seconds=30)
        if person.state == "reconnecting":
            person.state = "accepted"
    db.commit()
    assert any(person["state"] == "reconnecting" for person in service.get_call(db, owner, call["call_id"])["participants"])
    for person in db.query(SnapCallParticipant).filter_by(call_id=call["call_id"]).all():
        person.last_seen = datetime.now(timezone.utc) - timedelta(seconds=120)
    db.commit()
    failed = service.get_call(db, owner, call["call_id"])
    assert failed["state"] == "failed"
    assert failed["ended_reason"] == "network_timeout"
    with pytest.raises(HTTPException) as err:
        service.reconnect_call(db, owner, call["call_id"])
    assert err.value.status_code == 409


def test_decline_and_hangup(db):
    owner, peer = user("owner"), user("peer")
    contact = service.request_contact(db, owner, peer.user_id)
    service.respond_contact(db, peer, contact["contact_id"], True)
    conversation = service.create_direct(db, owner, peer.user_id)["conversation_id"]
    call = service.start_call(db, owner, conversation, "audio")
    declined = service.decline_call(db, peer, call["call_id"])
    assert declined["state"] == "declined"
    with pytest.raises(HTTPException):
        service.post_signal(db, owner, call["call_id"], kind="offer", payload="v=0", client_signal_id="signal-after-end")
    second = service.start_call(db, owner, conversation, "audio")
    service.accept_call(db, peer, second["call_id"])
    ended = service.end_call(db, owner, second["call_id"])
    assert ended["state"] == "ended"
    assert ended["ended_reason"] == "hangup"


def test_camera_draft_share_is_private_and_consent_based(db, monkeypatch, tmp_path):
    monkeypatch.setenv("SNAP_MEDIA_DIR", str(tmp_path))
    owner, peer, stranger = user("owner"), user("peer"), user("stranger")
    contact = service.request_contact(db, owner, peer.user_id)
    service.respond_contact(db, peer, contact["contact_id"], True)
    conversation = service.create_direct(db, owner, peer.user_id)["conversation_id"]
    with pytest.raises(HTTPException) as err:
        service.save_capture(db, owner, data=b"<html>no</html>", declared_type="text/html", duration_ms=0)
    assert err.value.status_code == 400
    with pytest.raises(HTTPException) as err:
        service.save_capture(db, owner, data=JPEG + b"x" * policy.MAX_PHOTO_BYTES, declared_type="image/jpeg", duration_ms=0)
    assert err.value.status_code == 413
    with pytest.raises(HTTPException) as err:
        service.save_capture(db, owner, data=b"\x1a\x45\xdf\xa3" + b"v" * 20, declared_type="video/webm", duration_ms=20000)
    assert err.value.status_code == 422
    saved = service.save_capture(db, owner, data=JPEG, declared_type="image/jpeg", duration_ms=0)
    assert saved["status"] == "draft"
    assert saved["public_url"] is None
    with pytest.raises(HTTPException) as err:
        service.share_capture(db, owner, saved["capture_id"], conversation, False)
    assert err.value.status_code == 400
    with pytest.raises(HTTPException):
        service.open_capture(db, peer, saved["capture_id"])
    shared = service.share_capture(db, owner, saved["capture_id"], conversation, True)
    assert shared["status"] == "shared"
    _row, path = service.open_capture(db, peer, saved["capture_id"])
    assert Path(path).read_bytes() == JPEG
    with pytest.raises(HTTPException):
        service.open_capture(db, stranger, saved["capture_id"])
    service.delete_capture(db, owner, saved["capture_id"])
    assert not Path(path).exists()
    with pytest.raises(HTTPException):
        service.open_capture(db, peer, saved["capture_id"])


def test_remove_my_content_keeps_blocks_and_clears_my_messages(db, monkeypatch, tmp_path):
    monkeypatch.setenv("SNAP_MEDIA_DIR", str(tmp_path))
    owner, peer = user("owner"), user("peer")
    contact = service.request_contact(db, owner, peer.user_id)
    service.respond_contact(db, peer, contact["contact_id"], True)
    conversation = service.create_direct(db, owner, peer.user_id)["conversation_id"]
    service.post_message(db, owner, conversation, "mine", "client-mine-0001")
    service.post_message(db, peer, conversation, "theirs", "client-peer-0001")
    service.save_capture(db, owner, data=PNG, declared_type="image/png", duration_ms=0)
    service.block_user(db, owner, "someone-else")
    result = service.remove_my_content(db, owner)
    assert result["messages_removed"] == 1
    assert result["captures_removed"] == 1
    assert result["blocks_kept"] is True
    visible = service.list_messages(db, peer, conversation)
    mine = [row for row in visible if row["sender_user_id"] == "owner"][0]
    theirs = [row for row in visible if row["sender_user_id"] == "peer"][0]
    assert mine["removed"] is True
    assert theirs["body"] == "theirs"
    assert service.list_captures(db, owner) == []


def test_page_requires_auth_and_camera_policy_stays_on_snap(monkeypatch):
    monkeypatch.delenv("SNAP_TURN_CREDENTIAL", raising=False)
    client = TestClient(app)
    page = client.get("/nova/snap")
    assert page.status_code == 200
    assert "Nova Snap" in page.text
    assert "Not a production release" in page.text
    assert "getDisplayMedia" not in page.text
    assert "Synapse Meeting" in page.text
    policy_header = page.headers["permissions-policy"]
    assert "camera=(self)" in policy_header
    assert "microphone=(self)" in policy_header
    assert "display-capture=()" in policy_header
    assert "camera=()" in client.get("/nova/workspace").headers["permissions-policy"]
    status = client.get("/api/nova/snap/status").json()
    assert status["turn_configured"] is False
    assert "credential" not in status
    assert client.get("/api/nova/snap/conversations").status_code == 401
    assert client.post("/api/nova/snap/calls", json={"conversation_id": "x", "media": "audio"}).status_code == 401
    assert client.post("/api/nova/snap/captures").status_code == 401


def _headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_two_account_synthetic_journey(monkeypatch, tmp_path):
    monkeypatch.setenv("SNAP_MEDIA_DIR", str(tmp_path))
    ensure_auth_schema()
    seed_default_users()
    service.reset_limits()
    client = TestClient(app)
    owner = _headers(client, "dispatcher@amicor.local")
    peer = _headers(client, "staff@amicor.local")
    outsider = _headers(client, "driver@amicor.local")
    missing = client.post("/api/nova/snap/contacts", headers=owner, json={"email": "nobody@example.com"})
    assert missing.status_code == 404
    created = client.post("/api/nova/snap/contacts", headers=owner, json={"email": "staff@amicor.local"})
    assert created.status_code == 200, created.text
    contact_id = created.json()["contact_id"]
    assert client.post("/api/nova/snap/contacts/" + contact_id + "/respond", headers=peer, json={"accept": True}).status_code == 200
    direct = client.post("/api/nova/snap/conversations/direct", headers=owner, json={"user_id": created.json()["peer_user_id"]})
    assert direct.status_code == 200, direct.text
    conversation = direct.json()["conversation_id"]
    assert client.get(f"/api/nova/snap/conversations/{conversation}/messages", headers=outsider).status_code == 404
    sent = client.post(
        f"/api/nova/snap/conversations/{conversation}/messages",
        headers=owner,
        json={"body": "Two account hello https://example.com", "client_message_id": "journey-msg-01"},
    )
    assert sent.status_code == 200, sent.text
    retry = client.post(
        f"/api/nova/snap/conversations/{conversation}/messages",
        headers=owner,
        json={"body": "Two account hello https://example.com", "client_message_id": "journey-msg-01"},
    )
    assert retry.json()["duplicate"] is True
    seen = client.get(f"/api/nova/snap/conversations/{conversation}/messages", headers=peer)
    assert seen.status_code == 200
    assert seen.json()[0]["body"].startswith("Two account hello")
    call = client.post("/api/nova/snap/calls", headers=owner, json={"conversation_id": conversation, "media": "audio"})
    assert call.status_code == 200, call.text
    call_id = call.json()["call_id"]
    assert client.get("/api/nova/snap/calls/incoming", headers=peer).json()[0]["call_id"] == call_id
    assert client.post(f"/api/nova/snap/calls/{call_id}/accept", headers=peer).status_code == 200
    signal = client.post(
        f"/api/nova/snap/calls/{call_id}/signals",
        headers=owner,
        json={"kind": "offer", "payload": "v=0", "client_signal_id": "journey-signal-1"},
    )
    assert signal.status_code == 200, signal.text
    assert client.get(f"/api/nova/snap/calls/{call_id}/signals", headers=peer).json()[0]["payload"] == "v=0"
    assert client.post(f"/api/nova/snap/calls/{call_id}/end", headers=peer).json()["state"] == "ended"
    files = {"upload": ("snap.jpg", JPEG, "image/jpeg")}
    draft = client.post("/api/nova/snap/captures", headers=owner, files=files, data={"duration_ms": "0"})
    assert draft.status_code == 200, draft.text
    capture_id = draft.json()["capture_id"]
    refused = client.post(
        f"/api/nova/snap/captures/{capture_id}/share",
        headers=owner,
        json={"conversation_id": conversation, "consent": False},
    )
    assert refused.status_code == 400
    shared = client.post(
        f"/api/nova/snap/captures/{capture_id}/share",
        headers=owner,
        json={"conversation_id": conversation, "consent": True},
    )
    assert shared.status_code == 200, shared.text
    media = client.get(f"/api/nova/snap/captures/{capture_id}/media", headers=peer)
    assert media.status_code == 200
    assert media.content == JPEG
    assert "attachment" in media.headers["content-disposition"].lower()
    assert client.get(f"/api/nova/snap/captures/{capture_id}/media", headers=outsider).status_code == 404
    assert client.post("/api/nova/snap/privacy/remove-my-content", headers=owner).status_code == 200
    assert client.get(f"/api/nova/snap/captures/{capture_id}/media", headers=peer).status_code == 404
