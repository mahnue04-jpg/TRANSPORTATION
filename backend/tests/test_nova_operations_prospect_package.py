import json
import zipfile
import pytest
from app.core.nova.work_revenue.operations_prospect_package import prepare_queue,restore_package

def test_navigation_only_candidates_are_held_and_messages_stay_drafts():
    m={'records':[{'business':'Navigation only','source_url':'https://example.com','status':'WORKFLOW_FIT_REQUIRES_QUALIFICATION','evidence':[{'signal':'group_travel','excerpt':'Home About Group Travel Contact'}]},
                  {'business':'Service context','source_url':'https://other.com','checked_at':'2026-11-13','status':'WORKFLOW_FIT_REQUIRES_QUALIFICATION','evidence':[{'signal':'consultation','excerpt':'Schedule a consultation'}]}],'failures':[]}
    q=prepare_queue(m)
    assert len(q['drafts'])==1 and len(q['holds'])==1
    assert q['drafts'][0]['can_send'] is False and q['messages_sent']==0
    assert len(q['drafts'][0]['required_before_sending'])==4

def test_recovery_rejects_traversal_or_incomplete_bundle(tmp_path):
    p=tmp_path/'bad.zip'
    with zipfile.ZipFile(p,'w') as z:z.writestr('../escape','bad')
    with pytest.raises(ValueError,match='Unexpected'):restore_package(p,tmp_path/'restored')
    assert not (tmp_path/'escape').exists()

def test_recovery_detects_changed_output(tmp_path):
    import hashlib
    p=tmp_path/'tampered.zip'
    files={'prospects.csv':b'original','outreach-queue.json':b'{}','README.txt':b'note'}
    receipt={'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
    files['prospects.csv']=b'changed'
    with zipfile.ZipFile(p,'w') as z:
        for k,v in files.items():z.writestr(k,v)
        z.writestr('backup-manifest.json',json.dumps(receipt))
    with pytest.raises(ValueError,match='integrity'):restore_package(p,tmp_path/'restored')
