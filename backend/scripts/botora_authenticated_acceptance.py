"""Local JWT integration acceptance, with disposable users and database only.

No dependency overrides, hosted credentials, external messaging, or paid APIs.
Private test secrets/tokens are never printed or included in the evidence.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import secrets

p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--resume',action='store_true');p.add_argument('--network',action='store_true');args=p.parse_args()
root=Path(args.directory).resolve()
if args.resume:
    if not root.is_dir():raise RuntimeError('Existing isolated acceptance directory required')
else:root.mkdir(parents=True,mode=0o700,exist_ok=False)
secret_path=root/'private-test-secrets.json'
if args.resume:credentials=json.loads(secret_path.read_text())
else:
    credentials={'password':secrets.token_urlsafe(32),'jwt':secrets.token_urlsafe(48)}
    fd=os.open(secret_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(credentials,f)
os.environ.update({'APP_ENV':'test','AMICOR_ENVIRONMENT':'test','TESTING':'true',
                   'DATABASE_URL':'sqlite:///'+str(root/'isolated-auth.db'),
                   'DB_FILENAME':str(root/'isolated-auth.db'),
                   'AMICOR_SEED_PASSWORD':credentials['password'],'JWT_SECRET':credentials['jwt'],
                   'SECRET_KEY':credentials['jwt'],'NOVA_V3_OWNER_EMAILS':'admin@amicor.local',
                   'NOVA_PROSPECT_REVIEW_DEVELOPMENT_ENABLED':'true',
                   'NOVA_PROSPECT_REVIEW_DIRECTORY':str(root/'private-research')})
logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from app.main import app
from app.auth import ensure_auth_schema,seed_default_users
from app.db.session import init_platform_db

if args.network:
    import atexit
    import socket
    import subprocess
    import sys
    import time
    import httpx
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(64)
    port=listener.getsockname()[1]
    server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--fd',str(listener.fileno()),'--lifespan','off','--no-access-log','--log-level','critical'],pass_fds=(listener.fileno(),),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    listener.close()
    def stop_server():
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait()
    atexit.register(stop_server)
    client=httpx.Client(base_url='http://127.0.0.1:'+str(port),timeout=90,trust_env=False)
    for attempt in range(100):
        if server.poll() is not None:raise RuntimeError('Isolated HTTP process exited')
        try:
            client.get('/api/nova/work/prospect-review/readiness');break
        except httpx.TransportError:time.sleep(.1)
    else:raise RuntimeError('Isolated HTTP server did not become reachable')
else:client=TestClient(app)
assert not app.dependency_overrides,'Authentication overrides must not be present'
base='/api/nova/work/prospect-review'
if args.resume:
    private=json.loads((root/'private-session.json').read_text())
    job=private['job_id']
    login=client.post('/api/auth/login',json={'email':'admin@amicor.local','password':credentials['password']})
    assert login.status_code==200,'Fresh owner sign-in for saved assignment failed'
    token=login.json()['access_token']
else:
    init_platform_db();ensure_auth_schema();seed_default_users()
    denied=client.get(base+'/readiness')
    assert denied.status_code in {401,403},'Anonymous request was not denied'
    login=client.post('/api/auth/login',json={'email':'admin@amicor.local','password':credentials['password']})
    assert login.status_code==200,'Isolated owner login failed'
    token=login.json()['access_token']
    headers={'Authorization':'Bearer '+token}
    ready=client.get(base+'/readiness',headers=headers)
    assert ready.status_code==200,'Owner readiness failed'
    body={'request_key':'authenticated-botora-1113','sources':[{'name':'Osiris Tours','url':'https://www.osiristours.com/contact-us/'}]}
    create=client.post(base+'/jobs',json=body,headers={**headers,'X-Nova-Owner-Action':'review-public-prospect-sources'})
    assert create.status_code==200,'Authenticated source processing failed'
    result=create.json();assert result['operations']['output_rows']==1,'Expected one actual public source record'
    job=result['job_id']
    replay=client.post(base+'/jobs',json=body,headers={**headers,'X-Nova-Owner-Action':'review-public-prospect-sources'})
    assert replay.status_code==200 and replay.json()['replayed'],'Duplicate request did not reuse output'
    other=client.post('/api/auth/login',json={'email':'dispatcher@amicor.local','password':credentials['password']})
    assert other.status_code==200,'Isolated non-owner login failed'
    other_headers={'Authorization':'Bearer '+other.json()['access_token']}
    assert client.get(base+'/jobs/'+job,headers=other_headers).status_code==403,'Non-owner access was not denied'
    assert client.get(base+'/jobs/'+job+'/review.csv',headers=other_headers).status_code==403,'Non-owner download was not denied'
    fd=os.open(root/'private-session.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'token':token,'job_id':job},f)
headers={'Authorization':'Bearer '+token}
listing=client.get(base+'/jobs',headers=headers)
assert listing.status_code==200 and any(r['job_id']==job for r in listing.json()['jobs']),'Saved assignment was not discoverable after fresh sign-in'
saved=client.get(base+'/jobs/'+job,headers=headers)
assert saved.status_code==200,'Signed saved-job retrieval failed'
download=client.get(base+'/jobs/'+job+'/review.csv',headers=headers)
assert download.status_code==200 and b'Osiris Tours' in download.content,'Signed download failed'
(root/'operations-auth-review.csv').write_bytes(download.content)
prepared=client.get(base+'/jobs/'+job+'/preparation',headers=headers)
assert prepared.status_code==200,'Owner preparation failed'
queue=prepared.json()
assert queue['owner_approval']=='PENDING' and queue['messages_sent']==0
assert all(d['can_send'] is False for d in queue['drafts'])
package=client.get(base+'/jobs/'+job+'/work-package.zip',headers=headers)
assert package.status_code==200 and package.headers['cache-control']=='no-store'
from io import BytesIO
from zipfile import ZipFile
with ZipFile(BytesIO(package.content)) as bundle:
    assert set(bundle.namelist())=={'prospects.csv','outreach-queue.json','README.txt','backup-manifest.json'}
    assert json.loads(bundle.read('outreach-queue.json'))==queue
other=client.post('/api/auth/login',json={'email':'dispatcher@amicor.local','password':credentials['password']})
assert other.status_code==200
other_headers={'Authorization':'Bearer '+other.json()['access_token']}
for endpoint in ['/preparation','/work-package.zip']:
    assert client.get(base+'/jobs/'+job+endpoint,headers=other_headers).status_code==403
    assert client.get(base+'/jobs/'+job+endpoint).status_code in {401,403}
(root/'operations-auth-work-package.zip').write_bytes(package.content)
evidence={'authentication':'REAL_LOCAL_JWT_LOGIN_WITH_DISPOSABLE_TEST_USERS','dependency_overrides':False,
          'application':'app.main:app','app_lifespan_started':False,'transport':'LOOPBACK_HTTP_SEPARATE_SERVER_PROCESS' if args.network else 'IN_PROCESS_HTTP_NOT_HOSTED',
          'saved_job_list_verified':True,'package_download_verified':True,'preparation_verified':True,'package_non_owner_denied':True,
          'package_anonymous_denied':True,'draft_count':len(queue['drafts']),
          'database':'ISOLATED_LOCAL_SQLITE_TEST_ONLY','job_id':job,'download_status':download.status_code,
          'review_status':saved.json()['owner_review'],'fresh_process_saved_job_verified':args.resume,'fresh_owner_login_on_resume':args.resume,
          'production_verified':False,'hosted_storage_verified':False,'outreach_sent':0}
if not args.resume:evidence.update({'anonymous_denied':True,'non_owner_read_denied':True,'non_owner_download_denied':True,'retry_reused_result':True})
else:
    old=json.loads((root/'acceptance.json').read_text());evidence={**old,**evidence}
evidence.pop('fresh_process_token_and_output_verified',None)
(root/'acceptance.json').write_text(json.dumps(evidence,indent=2))
print(json.dumps(evidence,indent=2))
