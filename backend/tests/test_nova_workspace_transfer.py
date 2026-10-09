from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.auth import UserContext
from app.core.nova.workspace import service, transfers
from app.core.nova.workspace.models import NovaWorkspaceTransfer, NovaWorkspaceProject, NovaWorkspaceFile
from app.core.nova.workspace.schemas import NovaWorkspaceProjectCreate, NovaWorkspaceFileCreate, NovaWorkspaceConversationCreate, NovaWorkspaceTransferCreate
from app.helpers import now


def actor(name, org):
    return UserContext(user_id=name, email=name + '@example.com', role='staff', organization_id=org)


def test_transfer_copies_snapshot_only_to_recipient_without_duplicates(db):
    sender, receiver, outsider = actor('sender', 'A'), actor('receiver', 'B'), actor('outsider', 'C')
    project = service.create_project(db, NovaWorkspaceProjectCreate(title='Easy Care onboarding', description='Blank training tracker'), organization_id='A', user=sender)
    file = service.add_file(db, NovaWorkspaceFileCreate(filename='tracker.txt', excerpt='Draft checklist', workspace_id=project.workspace_id, upload_id='private-upload'), organization_id='A', user=sender)
    convo = service.create_conversation(db, NovaWorkspaceConversationCreate(title='Testing drafts', workspace_id=project.workspace_id), organization_id='A', user=sender)
    service.append_message(db, convo.conversation_id, organization_id='A', user=sender, role='assistant', content='Somali and English draft')
    offer = transfers.prepare(db, project.workspace_id, 'RECEIVER@example.com', True, True, organization_id='A', user=sender)
    repeated = transfers.prepare(db, project.workspace_id, 'receiver@example.com', True, True, organization_id='A', user=sender)
    assert repeated['transfer_id'] == offer['transfer_id']
    assert transfers.incoming(db, user=outsider) == []
    with pytest.raises(service.NovaWorkspaceError) as denied:
        transfers.accept(db, offer['transfer_id'], organization_id='C', user=outsider)
    assert denied.value.status_code == 404
    assert transfers.incoming(db, user=receiver)[0]['file_text_count'] == 1
    project.description = 'Changed after preparation'
    db.commit()
    accepted = transfers.accept(db, offer['transfer_id'], organization_id='B', user=receiver)
    duplicate = transfers.accept(db, offer['transfer_id'], organization_id='B', user=receiver)
    assert duplicate['destination_workspace_id'] == accepted['destination_workspace_id']
    copied = service.get_project(db, accepted['destination_workspace_id'], organization_id='B', user=receiver)
    assert copied.description == 'Blank training tracker'
    assert copied.owner_user_id == receiver.user_id
    copied_files = service.list_files(db, organization_id='B', user=receiver, workspace_id=copied.workspace_id)
    assert copied_files[0].excerpt == 'Draft checklist'
    assert copied_files[0].upload_id is None
    conversations = service.list_conversations(db, organization_id='B', user=receiver, workspace_id=copied.workspace_id)
    _, messages = service.get_conversation(db, conversations[0][0].conversation_id, organization_id='B', user=receiver)
    assert messages[0].content == 'Somali and English draft'
    assert db.query(NovaWorkspaceProject).filter_by(organization_id='B').count() == 1
    assert service.get_file(db, file.file_id, organization_id='A', user=sender).upload_id == 'private-upload'
    with pytest.raises(service.NovaWorkspaceError):
        service.get_project(db, copied.workspace_id, organization_id='A', user=sender)


def test_transfer_ownership_cancel_expiry_and_optional_content(db):
    sender, receiver = actor('sender', 'A'), actor('receiver', 'B')
    project = service.create_project(db, NovaWorkspaceProjectCreate(title='Blank setup'), organization_id='A', user=sender)
    admin = actor('admin', 'A').model_copy(update={'role': 'admin'})
    with pytest.raises(service.NovaWorkspaceError) as denied:
        transfers.prepare(db, project.workspace_id, receiver.email, False, False, organization_id='A', user=admin)
    assert denied.value.status_code == 403
    offer = transfers.prepare(db, project.workspace_id, receiver.email, False, False, organization_id='A', user=sender)
    assert offer['conversation_count'] == offer['file_text_count'] == 0
    transfers.cancel(db, offer['transfer_id'], organization_id='A', user=sender)
    with pytest.raises(service.NovaWorkspaceError) as denied:
        transfers.accept(db, offer['transfer_id'], organization_id='B', user=receiver)
    assert denied.value.status_code == 410
    refreshed = transfers.prepare(db, project.workspace_id, receiver.email, False, False, organization_id='A', user=sender)
    assert refreshed['transfer_id'] != offer['transfer_id']
    row = db.query(NovaWorkspaceTransfer).filter_by(transfer_id=refreshed['transfer_id']).one()
    row.expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert transfers.incoming(db, user=receiver) == []
    with pytest.raises(service.NovaWorkspaceError) as denied:
        transfers.accept(db, refreshed['transfer_id'], organization_id='B', user=receiver)
    assert denied.value.status_code == 410
    assert db.query(NovaWorkspaceProject).filter_by(organization_id='B').count() == 0
    with pytest.raises(ValueError):
        NovaWorkspaceTransferCreate(workspace_id=project.workspace_id, recipient_email='invalid')


def test_somali_and_bilingual_prompts_preserve_source_facts(monkeypatch):
    prompts = []
    monkeypatch.setattr('app.ai.ask_openai', lambda prompt: prompts.append(prompt) or 'Qoraal tijaabo ah')
    assert service._answer_workspace_task('Samee liiska tababarka', 'PCA code; original note', 'so') == 'Qoraal tijaabo ah'
    assert 'Answer in Somali' in prompts[-1]
    assert 'Do not invent' in prompts[-1]
    service._answer_workspace_task('Translate this', 'Original note', 'bilingual')
    assert 'both English and Somali' in prompts[-1]
    assert 'Never rewrite original saved records' in prompts[-1]


def test_recorded_somali_returns_original_text_and_provider_failure(monkeypatch):
    from app.core.nova.workspace.router import transcribe_speech
    captured = []
    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(text='Waxaan rabaa liiska tababarka.')
    monkeypatch.setattr('app.ai.get_client', lambda: SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))))
    def audio(mime='audio/webm', data=b'recorded audio'):
        return UploadFile(BytesIO(data), filename='speech', headers=Headers({'content-type': mime}))
    result = transcribe_speech(audio(), actor('receiver', 'B'))
    assert result['text'] == 'Waxaan rabaa liiska tababarka.'
    assert result['review_required'] is True
    assert 'language' not in captured[0]
    assert 'Somali' in captured[0]['prompt']
    transcribe_speech(audio(), actor('receiver', 'B'), language='ar')
    assert captured[-1]['language'] == 'ar'
    assert captured[0]['model'] == 'gpt-4o-transcribe'
    with pytest.raises(HTTPException) as invalid:
        transcribe_speech(audio('text/plain'), actor('receiver', 'B'))
    assert invalid.value.status_code == 415
    def fail():
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr('app.ai.get_client', fail)
    with pytest.raises(HTTPException) as unavailable:
        transcribe_speech(audio(), actor('receiver', 'B'))
    assert unavailable.value.status_code == 503


def test_transfer_migration_is_idempotent_and_matches_model():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/20261009_nova_ws_transfer.py'
    spec = importlib.util.spec_from_file_location('transfer_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine('sqlite:///:memory:').begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            assert {c['name'] for c in inspect(connection).get_columns('nova_workspace_transfers')} == set(NovaWorkspaceTransfer.__table__.columns.keys())
            migration.downgrade()
            assert 'nova_workspace_transfers' not in inspect(connection).get_table_names()
