from __future__ import annotations

import time

from app import main


def test_assistant_preview_confirm_uses_local_replay_fallback(monkeypatch):
    monkeypatch.setattr(main, "_get_assistant_redis", lambda required=False: None)

    with main._assistant_local_replay_lock:
        main._assistant_local_confirmation_tokens.clear()
        main._assistant_local_preview_records.clear()
        main._assistant_local_nonce_consumed.clear()
        main._assistant_local_request_digests.clear()
        main._assistant_local_intent_hashes.clear()

    expires_at = int(time.time()) + 3600
    claims = {
        "jti": "token-123",
        "intent_id": "intent-123",
        "action_type": "preview",
        "user_id": "user-123",
        "session_id": "session-123",
        "intent_hash": "intent-hash-123",
        "nonce": "nonce-123",
        "issued_at": int(time.time()),
        "expires_at": expires_at,
        "dry_run_only": True,
        "supervision_classification": "supervision_enforced",
    }
    policy = {
        "policy_version": "1.0",
        "policy_scope": "assistant_preview",
        "policy_state": "ALLOWED",
        "sensitivity_tier": "low",
    }
    preview_payload = {"intent_id": "intent-123", "preview_payload_json": "{}"}

    main._redis_store_confirmation_token(claims, "signed-token", policy, "corr-123")
    main._redis_store_preview_record("intent-123", preview_payload, expires_at)

    stored_token = main._redis_get_confirmation_token("token-123")
    stored_preview = main._redis_get_preview_record("intent-123")

    assert stored_token is not None
    assert stored_token["signed_token"] == "signed-token"
    assert stored_preview is not None
    assert stored_preview["intent_id"] == "intent-123"

    consume_result = main._redis_consume_confirmation_guards(
        "token-123",
        "nonce-123",
        "request-hash-123",
        "intent-hash-123",
        expires_at,
    )
    replay_result = main._redis_consume_confirmation_guards(
        "token-123",
        "nonce-123",
        "request-hash-123",
        "intent-hash-123",
        expires_at,
    )

    assert consume_result == "OK"
    assert replay_result != "OK"
