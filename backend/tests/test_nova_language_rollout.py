"""Rollout languages stay unverified for Work & Revenue and the Operations Agent."""

import pytest
from fastapi import HTTPException

from app.auth import UserContext
from app.core.nova.language import models as language_models  # noqa: F401
from app.core.nova.language import router as language
from app.core.nova.language.guards import (
    assess_operations_task,
    guard_proposal,
    opportunity_language_plan,
)
from app.core.nova.language.models import NovaLanguagePreference
from app.core.nova.work_revenue.international_match import assess_international_match


def user(role="admin"):
    return UserContext(user_id="owner", email="owner@example.com", role=role, organization_id="org")


def response():
    return type("R", (), {"headers": {}})()


def listing(description):
    return {"title": "Remote operations", "description": description, "company_name": "Example Co"}


@pytest.mark.parametrize("code", ["ja", "ko", "el", "ru", "de"])
def test_rollout_preference_is_saved_and_not_operational(db, code):
    caller = user()
    saved = language.update_language(language.LanguageUpdate(screen_language=code), response(), caller, db)
    assert saved["screen_language"] == code
    assert saved["persisted"] is True
    assert saved["operational"] is False
    assert saved["business_delivery_operational"] is False
    assert saved["business_delivery_mode"] == "not_verified"
    assert saved["translation_verified"] is False
    assert saved["voice_interpretation"] is False
    assert saved["bidirectional_text"] is False
    assert saved["notice"]
    assert caller.role == "admin"
    assert "role" not in saved
    again = language.read_language(response(), caller, db)
    assert again["screen_language"] == code
    assert again["operational"] is False


def test_verified_screen_language_stays_ai_assisted_and_untranslated(db):
    caller = user(role="staff")
    saved = language.update_language(language.LanguageUpdate(screen_language="fr"), response(), caller, db)
    assert saved["operational"] is True
    assert saved["business_delivery_mode"] == "ai_assisted_text"
    assert saved["translation_verified"] is False
    assert saved["voice_interpretation"] is False
    assert caller.role == "staff"
    row = db.get(NovaLanguagePreference, caller.user_id)
    assert row.screen_language == "fr"


def test_unknown_language_is_still_refused(db):
    caller = user()
    with pytest.raises(HTTPException) as unsupported:
        language.update_language(language.LanguageUpdate(screen_language="zh"), response(), caller, db)
    assert unsupported.value.status_code == 422
    assert db.get(NovaLanguagePreference, caller.user_id) is None


@pytest.mark.parametrize(
    ("sentence", "code"),
    [
        ("Remote B2B administrative support. Japanese fluency required.", "ja"),
        ("Remote B2B administrative support. Korean fluency required.", "ko"),
        ("Remote B2B administrative support. Greek fluency required.", "el"),
        ("Remote B2B administrative support. Russian fluency required.", "ru"),
        ("Remote B2B administrative support. German fluency required.", "de"),
    ],
)
def test_discovery_fails_closed_for_unverified_business_languages(sentence, code):
    plan = opportunity_language_plan(sentence)
    assert plan["fail_closed"] is True
    assert code in plan["unverified_required"]
    assert plan["translation_applied"] is False
    assert plan["original_language_preserved"] is True
    assert plan["business_delivery_operational"] is False
    assessed = assess_international_match(listing(sentence))
    assert "untested_language_required" in assessed["blockers"]
    assert assessed["language_support_label"] == ""
    assert assessed["language_rollout"]["fail_closed"] is True


def test_french_or_german_keeps_the_french_path_and_leaves_german_unverified():
    sentence = "Remote B2B administrative support. French or German required."
    plan = opportunity_language_plan(sentence)
    assert plan["fail_closed"] is False
    assert "de" in plan["unverified_alternatives"]
    assert "de" not in plan["unverified_required"]
    assert plan["translation_applied"] is False
    assessed = assess_international_match(listing(sentence))
    assert assessed["language_support_label"] == "AI-assisted translation"
    assert "untested_language_required" not in assessed["blockers"]


def test_preferred_japanese_does_not_qualify_japanese_delivery():
    plan = opportunity_language_plan("Remote research support. Japanese preferred.")
    assert plan["fail_closed"] is False
    assert plan["preferred_unverified"] == ["ja"]
    assert plan["translation_applied"] is False


def test_proposal_preserves_japanese_source_and_refuses_legal_translation():
    listing_text = (
        "請求書の整理をお願いします。Governing law of Japan applies. "
        "Client approval is required before submission."
    )
    draft = "INTERNAL DRAFT ONLY. Company: Example. Work: Invoice support."
    guarded = guard_proposal(listing_text, draft, "ja")
    assert guarded["source_text"] == listing_text
    assert guarded["source_language"] == "ja"
    assert guarded["proposal_language"] == "ja"
    assert guarded["translation_applied"] is False
    assert guarded["legal_terms_present"] is True
    assert guarded["legal_terms_translated"] is False
    assert guarded["client_approval_present"] is True
    assert guarded["client_approval_translated"] is False
    assert guarded["unsupported_translation_refused"] is True
    assert guarded["business_delivery_operational"] is False
    assert "請求書の整理をお願いします" not in guarded["body"]
    assert "Original language is preserved." in guarded["body"]
    assert "Legal terms were not translated." in guarded["body"]
    assert "Client approval text was not translated." in guarded["body"]


@pytest.mark.parametrize("code", ["ja", "ko", "el", "ru", "de"])
def test_operations_task_keeps_original_text_for_each_rollout_language(code):
    samples = {
        "ja": "請求書を確認し、client approval を待ってください。Governing law applies.",
        "ko": "인보이스를 확인하고 client approval 을 기다리세요. Governing law applies.",
        "el": "Ελέγξτε το τιμολόγιο και περιμένετε client approval. Governing law applies.",
        "ru": "Проверьте счёт и дождитесь client approval. Governing law applies.",
        "de": "Prüfen Sie die Rechnung und warten Sie auf client approval. Governing law applies.",
    }
    text = samples[code]
    result = assess_operations_task(text, code)
    assert result["output_text"] == text
    assert result["input_text"] == text
    assert result["source_language"] == code
    assert result["translation_applied"] is False
    assert result["legal_terms_translated"] is False
    assert result["client_approval_translated"] is False
    assert result["unsupported_translation_refused"] is True
    assert result["business_delivery_operational"] is False
    assert result["operational"] is False
    assert result["notice"]
    assert result["approval_copy"]["legal_not_translated"]
    assert result["approval_copy"]["client_approval_not_translated"]


def test_operations_route_returns_the_guard_without_a_role(db):
    del db
    caller = user()
    body = language.task_guard(
        language.TaskGuardIn(text="Bitte prüfen. Client approval required. Governing law applies.", requested_language="de"),
        response(),
        caller,
    )
    assert body["source_language"] == "de"
    assert body["output_text"].startswith("Bitte prüfen")
    assert body["translation_applied"] is False
    assert body["legal_terms_translated"] is False
    assert body["client_approval_translated"] is False
    assert "role" not in body
    assert caller.role == "admin"
