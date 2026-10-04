from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth import UserContext
from app.core.nova.agent_coordination import coordination_snapshot
from app.core.nova.work_revenue.models import NovaWorkOpportunity
from app.core.nova.today import service
from app.core.nova.today.schemas import NovaTodayBrainRequest
from app.core.nova.service import NovaCoreService


def test_handoff_filters_work_to_current_owner_and_organization(db, monkeypatch):
    monkeypatch.setattr('app.core.nova.agent_coordination.ensure_marketing_schema', lambda: None)
    user = UserContext(user_id='owner-a', email='owner@example.com', role='admin', organization_id='org-a')
    for ident, org, owner in [('visible', 'org-a', 'owner-a'), ('other-org', 'org-b', 'owner-a'), ('other-owner', 'org-a', 'owner-b')]:
        db.add(NovaWorkOpportunity(opportunity_id=ident, organization_id=org, owner_user_id=owner,
            company_name='Example', opportunity_title=ident, status='QUALIFIED', archived=False))
    db.commit()
    result = coordination_snapshot(db, organization_id='org-a', user=user)
    assert [row['opportunity_id'] for row in result['work_revenue_to_operations']] == ['visible']
    assert result['rules']['operations_agent_may_contact_prospect_from_feed'] is False


@pytest.mark.parametrize('authorized', [True, False])
def test_ask_nova_includes_handoff_only_after_owner_gate(monkeypatch, authorized):
    user = UserContext(user_id='owner-a', email='owner@example.com', role='admin', organization_id='org-a')
    dash = SimpleNamespace(attention_now=[], communications=[], government=[], business=[], workspace=[], approval_queue=[], recent_activity=[], connector_health={})
    monkeypatch.setattr(service, '_today_live_or_memory_answer', lambda *a, **k: None)
    monkeypatch.setattr(service, 'dashboard', lambda *a, **k: dash)
    monkeypatch.setattr(service, 'list_recheck_events', lambda *a, **k: [])
    def gate(**kwargs):
        if not authorized:
            raise HTTPException(status_code=403)
        return user
    import importlib
    work_router = importlib.import_module('app.core.nova.work_revenue.router')
    monkeypatch.setattr(work_router, 'require_work_revenue_owner', gate)
    calls = []
    def snapshot(*a, **k):
        calls.append(k)
        return {'work_revenue_to_operations': [{'title': 'Recorded contract'}]}
    monkeypatch.setattr('app.core.nova.agent_coordination.coordination_snapshot', snapshot)
    prompts = []
    def ask(*a, **kwargs):
        prompts.append(kwargs['question'])
        return SimpleNamespace(answer='Answer', context_used={}, next_actions=[], generated_at='2026-10-04T00:00:00Z')
    monkeypatch.setattr(NovaCoreService, 'ask', ask)
    service.ask_today(None, NovaTodayBrainRequest(question='Explain Operations Agent coordination'), organization_id='org-a', user=user)
    assert bool(calls) is authorized
    assert ('Recorded contract' in prompts[0]) is authorized
