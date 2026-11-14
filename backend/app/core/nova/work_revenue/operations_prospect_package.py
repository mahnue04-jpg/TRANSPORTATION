"""Supervised Operations deliverables and portable review-output recovery.

This does not send messages, approve campaigns or replace hosted app storage.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from .prospect_research import verify_saved_run, _private_write
from .operations_csv_cleanup import clean_csv_text

CONTEXT = re.compile(r'\b(?:consultation|custom(?:ized)?|we plan|we craft|itinerar\w*|request a|schedule a)\b',re.I)
GATES = ['Executed Botora agreement','Botora approval of this exact message and use case',
         'Owner launch authorization','Verified business contact and permitted outreach channel']


def prepare_queue(manifest):
    drafts=[];holds=[]
    for row in manifest['records']:
        evidence=[e for e in row.get('evidence',[]) if CONTEXT.search(e.get('excerpt',''))]
        if row['status']!='WORKFLOW_FIT_REQUIRES_QUALIFICATION' or not evidence:
            holds.append({'business':row['business'],'source_url':row['source_url'],
                          'reason':'Stronger service-intake evidence required; navigation keywords alone are insufficient'})
            continue
        signal=evidence[0]['signal']
        observation='Your website offers travel consultations.' if signal=='consultation' else 'Your website describes custom travel planning.'
        body=(f"Hello {row['business']} team,\n\n{observation} I wanted to ask how your team handles routine questions and collects details before a planning conversation.\n\n"
              "AMICOR is preparing a referral service with Botora for approved website enquiry and chatbot workflows. Would a short example be useful to your team? If so, which repetitive enquiry would you most like to simplify?\n\n"
              "If this is not relevant, please let me know and I will not follow up.\n\nSaye N. Monibah\nAMICOR HEALTH ISF LLC")
        drafts.append({'business':row['business'],'source_url':row['source_url'],'checked_at':row['checked_at'],
                       'evidence':evidence,'subject':'A question about your travel enquiries','body':body,
                       'contact':'NOT_YET_VERIFIED','buying_interest':'UNVERIFIED','introduction_consent':'NOT_OBTAINED',
                       'status':'DRAFT_FOR_OWNER_AND_BOTORA_REVIEW','can_send':False,
                       'required_before_sending':GATES,
                       'qualification_questions':['What enquiry volume or repetitive task needs improvement?',
                          'Which channels and existing tools do you use?','Who approves a solution?',
                          'What budget and start date are realistic?','If interested, may we introduce you to Botora?']})
    return {'mode':'SUPERVISED_RESEARCH_AND_DRAFT_PREPARATION','drafts':drafts,'holds':holds,
            'source_failures':manifest['failures'],'messages_sent':0,'owner_approval':'PENDING',
            'botora_approval':'PENDING','launch_approved':False,'hosted_product_verified':False,
            'historical_139_overlap':'UNKNOWN','recovery_scope':'Review outputs only; original fetched HTML and app authentication are not included'}


def build_package(run_directory,archive_path):
    verify_saved_run(run_directory)
    manifest=json.loads((Path(run_directory)/'manifest.json').read_text())
    queue=prepare_queue(manifest)
    stream=io.StringIO();writer=csv.writer(stream,lineterminator='\n')
    writer.writerow(['Business','Source URL','Operations status','Buying interest','Next action'])
    for r in queue['drafts']:writer.writerow([r['business'],r['source_url'],'DRAFT_REVIEW_REQUIRED','UNVERIFIED','Verify contact and obtain campaign/launch approval'])
    for r in queue['holds']:writer.writerow([r['business'],r['source_url'],'HOLD_FOR_STRONGER_EVIDENCE','UNVERIFIED',r['reason']])
    cleaned=clean_csv_text(stream.getvalue()).cleaned_csv.encode()
    files={'prospects.csv':cleaned,'outreach-queue.json':json.dumps(queue,indent=2).encode(),
           'README.txt':b'Owner review outputs only. No messages have been sent. This backup does not contain app credentials, a database, or original source HTML. Restore never approves outreach.\n'}
    receipt={'schema_version':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in files.items()},'messages_sent':0}
    files['backup-manifest.json']=json.dumps(receipt,indent=2).encode()
    out=Path(archive_path)
    with out.open('xb') as f:
        with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in files.items():z.writestr(name,data)
    out.chmod(0o600)
    return queue


def restore_package(archive_path,destination):
    expected={'prospects.csv','outreach-queue.json','README.txt','backup-manifest.json'}
    with zipfile.ZipFile(archive_path) as z:
        if set(z.namelist())!=expected or len(z.infolist())!=4:raise ValueError('Unexpected recovery bundle files')
        if sum(i.file_size for i in z.infolist())>5_000_000:raise ValueError('Recovery bundle exceeds size limit')
        files={name:z.read(name) for name in expected}
    receipt=json.loads(files['backup-manifest.json'])
    if set(receipt['files'])!=expected-{'backup-manifest.json'}:raise ValueError('Incomplete recovery receipt')
    for name,digest in receipt['files'].items():
        if hashlib.sha256(files[name]).hexdigest()!=digest:raise ValueError('Recovery integrity check failed')
    q=json.loads(files['outreach-queue.json'])
    if q.get('messages_sent')!=0 or q.get('owner_approval')!='PENDING' or q.get('launch_approved') is not False:
        raise ValueError('Recovery cannot grant approval or assert delivery')
    if any(r.get('can_send') is not False for r in q['drafts']):raise ValueError('Recovery cannot enable sending')
    root=Path(destination);root.mkdir(parents=True,mode=0o700,exist_ok=False)
    for name,data in files.items():_private_write(root/name,data)
    return {'restored_drafts':len(q['drafts']),'holds':len(q['holds']),'messages_sent':0,
            'owner_review':'PENDING','integrity_verified':True,'scope':'REVIEW_OUTPUTS_ONLY'}
