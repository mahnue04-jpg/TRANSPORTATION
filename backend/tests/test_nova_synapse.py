import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from app.auth import UserContext
from app.core.nova.synapse import router as synapse


def user(uid="owner", org="org"):
    return UserContext(user_id=uid, email=f"{uid}@example.com", role="admin", organization_id=org)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://meet.example.com")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret-with-at-least-thirty-two-characters")


def decode(token):
    return json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '=='))


def test_missing_provider_cannot_create_or_issue_token(db, monkeypatch):
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    assert synapse.status(Response())["configured"] is False
    with pytest.raises(HTTPException) as err:
        synapse.create(synapse.CreateMeeting(title="Test"), Response(), user(), db)
    assert err.value.status_code == 503
    assert synapse.provider_origin() == ""


@pytest.mark.parametrize('url',["http://meet.example.com", "wss://meet.example.com/a", "wss://meet.example.com?x=1", "wss://u:p@meet.example.com", "wss://meet.example.com;script-src evil.test"])
def test_provider_origin_rejects_unsafe_configuration(provider, monkeypatch, url):
    monkeypatch.setenv('LIVEKIT_URL',url)
    assert synapse.provider_config() is None


def test_invitation_grants_ownership_lock_and_expiry(db, provider):
    owner = user()
    created = synapse.create(synapse.CreateMeeting(title="Team"),Response(),owner,db)
    mid = created['meeting_id']
    invite = created['invite_path'].split('invite=')[1]
    stored = db.get(synapse.SynapseMeeting,mid)
    assert stored.invite_hash != invite
    assert 'invite' not in synapse.meetings(owner,db)[0]
    with pytest.raises(HTTPException) as err:
        synapse.host(mid,Response(),user("other"),db)
    assert err.value.status_code == 404
    with pytest.raises(HTTPException):
        synapse.host(mid,Response(),user("owner","another-org"),db)
    with pytest.raises(HTTPException):
        synapse.join(mid,synapse.GuestJoin(invite='x'*43,name='Visitor'),Response(),db)
    joined = synapse.join(mid,synapse.GuestJoin(invite=invite,name='Visitor'),Response(),db)
    claims = decode(joined['participant_token'])
    assert claims['video']['room'] == mid
    assert claims['video']['roomJoin'] is True
    assert claims['video']['roomAdmin'] is False
    assert claims['exp'] - claims['nbf'] == 305
    assert 'example.com' not in claims['sub']
    raw, sig = joined['participant_token'].rsplit('.',1)
    expected = base64.urlsafe_b64encode(hmac.new(b'test-secret-with-at-least-thirty-two-characters',raw.encode(),hashlib.sha256).digest()).rstrip(b'=').decode()
    assert hmac.compare_digest(sig,expected)
    assert decode(synapse.host(mid,Response(),owner,db)['participant_token'])['video']['roomAdmin'] is True
    synapse.lock(mid,synapse.LockMeeting(locked=True),owner,db)
    with pytest.raises(HTTPException) as err:
        synapse.join(mid,synapse.GuestJoin(invite=invite,name='Visitor'),Response(),db)
    assert err.value.status_code == 403
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException) as err:
        synapse.host(mid,Response(),owner,db)
    assert err.value.status_code == 410


def test_end_checks_provider_result_before_claiming_ended(db, provider, monkeypatch):
    owner = user()
    mid = synapse.create(synapse.CreateMeeting(title='Team'),Response(),owner,db)['meeting_id']
    monkeypatch.setattr(synapse.requests,'post',lambda *a,**kw: SimpleNamespace(status_code=503))
    with pytest.raises(HTTPException):
        synapse.end(mid,owner,db)
    assert db.get(synapse.SynapseMeeting,mid).ended is False
    monkeypatch.setattr(synapse.requests,'post',lambda *a,**kw: SimpleNamespace(status_code=200))
    assert synapse.end(mid,owner,db) == {'ended':True}
    with pytest.raises(HTTPException) as err:
        synapse.join(mid,synapse.GuestJoin(invite='x'*43,name='Visitor'),Response(),db)
    assert err.value.status_code == 410


def test_scoped_camera_and_media_policy(provider):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.middleware import SecurityHeadersMiddleware
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    @app.get('/{path:path}')
    def page(path):
        return {}
    client = TestClient(app)
    headers = client.get('/nova/synapse').headers
    assert 'camera=(self)' in headers['permissions-policy']
    assert "connect-src 'self' wss://meet.example.com https://meet.example.com;" in headers['content-security-policy']
    assert headers['referrer-policy'] == 'no-referrer'
    assert 'camera=()' in client.get('/nova/workspace').headers['permissions-policy']
    assert 'wss://meet.example.com' not in client.get('/nova/workspace').headers['content-security-policy']


def test_synapse_page_and_host_api_require_authentication(monkeypatch):
    from app.main import app
    from fastapi.testclient import TestClient
    monkeypatch.delenv('LIVEKIT_API_SECRET', raising=False)
    client = TestClient(app)
    page = client.get('/nova/synapse')
    assert page.status_code == 200
    assert 'AMICOR Synapse' in page.text
    assert '/static/nova-synapse/livekit-client.umd.min.js' in page.text
    assert client.get('/api/nova/synapse/status').json()['configured'] is False
    assert client.get('/api/nova/synapse/meetings').status_code == 401
    assert client.post('/api/nova/synapse/meetings',json={'title':'Private'}).status_code == 401
    assert client.post('/api/nova/synapse/meetings/unknown/host').status_code == 401
    assert client.post('/api/nova/synapse/meetings/unknown/end').status_code == 401


def test_resumed_host_can_rotate_invitation_without_extending_expiry(db, provider):
    owner = user()
    created = synapse.create(synapse.CreateMeeting(title='Team'),Response(),owner,db)
    mid = created['meeting_id']
    old = created['invite_path'].split('invite=')[1]
    with pytest.raises(HTTPException):
        synapse.invitation(mid,Response(),user('other'),db)
    renewed = synapse.invitation(mid,Response(),owner,db)
    new = renewed['invite_path'].split('invite=')[1]
    assert old != new
    assert renewed['expires_at'] == created['expires_at']
    with pytest.raises(HTTPException) as err:
        synapse.join(mid,synapse.GuestJoin(invite=old,name='Visitor'),Response(),db)
    assert err.value.status_code == 404
    assert synapse.join(mid,synapse.GuestJoin(invite=new,name='Visitor'),Response(),db)['host'] is False


def test_only_owner_can_rename_without_changing_invitation(db, provider):
    owner = user()
    created = synapse.create(synapse.CreateMeeting(title='AMICOR Synapse Test'), Response(), owner, db)
    mid = created['meeting_id']
    invite = created['invite_path'].split('invite=')[1]
    with pytest.raises(HTTPException) as err:
        synapse.rename(mid, synapse.CreateMeeting(title='Changed'), user('other'), db)
    assert err.value.status_code == 404
    with pytest.raises(HTTPException):
        synapse.rename(mid, synapse.CreateMeeting(title='Changed'), user('owner', 'another-org'), db)
    with pytest.raises(HTTPException) as err:
        synapse.rename(mid, synapse.CreateMeeting(title='   '), owner, db)
    assert err.value.status_code == 422
    renamed = synapse.rename(mid, synapse.CreateMeeting(title='Easy Care · Team meeting'), owner, db)
    assert renamed['title'] == 'Easy Care · Team meeting'
    assert renamed['expires_at'] == created['expires_at']
    assert synapse.join(mid, synapse.GuestJoin(invite=invite, name='Visitor'), Response(), db)['title'] == renamed['title']
