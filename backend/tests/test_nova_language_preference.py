import pytest
from fastapi import HTTPException

from app.auth import UserContext
from app.core.nova.language import models as language_models  # noqa: F401 — register the table
from app.core.nova.language import router as language
from app.core.nova.language.models import NovaLanguagePreference


def user(uid="owner", org="org", role="admin"):
    return UserContext(user_id=uid, email=f"{uid}@example.com", role=role, organization_id=org)


def test_account_preference_is_kept_for_the_same_account_and_hidden_from_another(db):
    caller = user()
    saved = language.update_language(language.LanguageUpdate(screen_language="fr"), type("R", (), {"headers": {}})(), caller, db)
    assert saved["screen_language"] == "fr"
    assert saved["persisted"] is True
    assert saved["voice_interpretation"] is False
    assert saved["bidirectional_text"] is False
    assert caller.role == "admin"

    again = language.read_language(type("R", (), {"headers": {}})(), caller, db)
    assert again["screen_language"] == "fr"
    assert again["persisted"] is True

    other = language.read_language(type("R", (), {"headers": {}})(), user("other"), db)
    assert other["screen_language"] == "en"
    assert other["persisted"] is False
    assert db.get(NovaLanguagePreference, "other") is None


def test_language_change_does_not_accept_another_account_or_an_unsupported_code(db):
    caller = user(role="staff")
    with pytest.raises(HTTPException) as unsupported:
        language.update_language(language.LanguageUpdate(screen_language="zh"), type("R", (), {"headers": {}})(), caller, db)
    assert unsupported.value.status_code == 422
    assert caller.role == "staff"
    assert db.get(NovaLanguagePreference, caller.user_id) is None

    language.update_language(language.LanguageUpdate(screen_language="es"), type("R", (), {"headers": {}})(), caller, db)
    row = db.get(NovaLanguagePreference, caller.user_id)
    assert row.screen_language == "es"
    assert row.user_id == caller.user_id
    assert "role" not in language.read_language(type("R", (), {"headers": {}})(), caller, db)


def test_language_routes_require_nova_access():
    assert language.router.dependencies
    paths = {route.path for route in language.router.routes}
    assert paths == {"/api/nova/language", "/api/nova/language/task-guard"}
