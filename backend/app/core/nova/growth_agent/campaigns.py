"""Studio-to-Growth handoff. No generation, publishing, messaging or task execution."""
from html import escape
from uuid import uuid4

from app.core.nova.creative_studio.db_models import NovaCreativeProject
from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.flags import _env_enabled, growth_agent_enabled, widget_public_enabled
from app.core.nova.growth_agent.models import GaCampaign, GaWidgetInstallation
from app.core.nova.growth_agent.widget_crypto import domain_allowed, hash_token, verify_installation_token


def require_campaigns():
    if not growth_agent_enabled() or not _env_enabled("NOVA_GROWTH_AGENT_CAMPAIGNS_ENABLED"):
        raise GrowthAgentError("DISABLED", "Campaign connection disabled", http_status=404)


class CampaignService:
    def __init__(self, growth):
        self.growth = growth
        self.db = growth.db

    def projects(self, owner_id):
        require_campaigns()
        return [{"id": p.id, "title": p.title} for p in self.db.query(NovaCreativeProject)
                .filter_by(owner_id=owner_id).order_by(NovaCreativeProject.updated_at.desc()).limit(200)]

    def _owned(self, org_id, owner_id, campaign_id):
        require_campaigns()
        row = self.db.query(GaCampaign).filter_by(
            id=campaign_id, organization_id=org_id, owner_id=owner_id).one_or_none()
        if not row:
            raise GrowthAgentError("NOT_FOUND", "Campaign unavailable", http_status=404)
        return row

    @staticmethod
    def summary(row):
        return {"id": row.id, "studio_project_id": row.studio_project_id,
                "title": row.title, "description": row.description, "status": row.status,
                "inquiry_path": f"/api/nova/growth-agent/campaigns/{row.id}/visit",
                "next_action": "Review inquiries in CRM" if row.status == "active" else "Review content and activate",
                "published": False, "live_delivery": False}

    def list(self, org_id, owner_id):
        require_campaigns()
        return [self.summary(c) for c in self.db.query(GaCampaign).filter_by(
            organization_id=org_id, owner_id=owner_id).order_by(GaCampaign.created_at.desc()).limit(200)]

    def _installation(self, token, org_id):
        claims = verify_installation_token(token)
        row = self.db.query(GaWidgetInstallation).filter_by(
            id=claims["installation_id"], organization_id=org_id, active=True).one_or_none()
        if claims["organization_id"] != org_id or not row or row.token_hash != hash_token(token):
            raise GrowthAgentError("NOT_FOUND", "Widget unavailable", http_status=404)
        return row

    def create(self, org_id, owner_id, data):
        require_campaigns()
        project = self.db.query(NovaCreativeProject).filter_by(
            id=data["studio_project_id"], owner_id=owner_id).one_or_none()
        if not project:
            raise GrowthAgentError("NOT_FOUND", "Studio project unavailable", http_status=404)
        self.growth._require_profile(org_id)
        install = self._installation(data["widget_token"], org_id)
        title, description = data["title"].strip(), data["description"].strip()
        if not title or not description:
            raise GrowthAgentError("VALIDATION", "Title and description required")
        row = GaCampaign(id=uuid4().hex, organization_id=org_id, owner_id=owner_id,
                         studio_project_id=project.id, widget_installation_id=install.id,
                         public_widget_token=data["widget_token"], title=title,
                         description=description, status="draft")
        self.db.add(row)
        self.growth.audit(org_id, action="campaign.create", entity_type="campaign", entity_id=row.id,
                          actor_user_id=owner_id, summary="Studio campaign saved for review")
        self.db.commit()
        return self.summary(row)

    def set_state(self, org_id, owner_id, campaign_id, active, content_approved):
        row = self._owned(org_id, owner_id, campaign_id)
        if active:
            if not content_approved:
                raise GrowthAgentError("APPROVAL_REQUIRED", "Review and approve campaign content before activation")
            profile = self.growth._require_profile(org_id)
            if not profile.activated or profile.agent_disabled:
                raise GrowthAgentError("NOT_ACTIVATED", "Activate the business profile first")
            self._installation(row.public_widget_token, org_id)
        row.status = "active" if active else "paused"
        self.growth.audit(org_id, action="campaign." + row.status, entity_type="campaign", entity_id=row.id,
                          actor_user_id=owner_id, summary="Owner changed campaign availability")
        self.db.commit()
        return self.summary(row)

    def active_campaign(self, campaign_id):
        require_campaigns()
        if not widget_public_enabled():
            raise GrowthAgentError("DISABLED", "Widget disabled", http_status=404)
        row = self.db.query(GaCampaign).filter_by(id=campaign_id, status="active").one_or_none()
        if not row:
            raise GrowthAgentError("NOT_FOUND", "Campaign unavailable", http_status=404)
        profile = self.growth._require_profile(row.organization_id)
        if not profile.activated or profile.agent_disabled:
            raise GrowthAgentError("NOT_FOUND", "Campaign unavailable", http_status=404)
        self._installation(row.public_widget_token, row.organization_id)
        return row

    def landing(self, campaign_id, origin):
        row = self.active_campaign(campaign_id)
        install = self._installation(row.public_widget_token, row.organization_id)
        if not domain_allowed(install.domain, origin):
            raise GrowthAgentError("ORIGIN_DENIED", "Open on the configured widget domain", http_status=403)
        return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(row.title)}</title><link rel="stylesheet" href="/static/nova-growth/growth.css"></head>
<body><main class="ga-main"><section class="panel"><h1>{escape(row.title)}</h1>
<p style="white-space:pre-wrap">{escape(row.description)}</p>
<p>Use “Chat with us” to ask a question or request help. AI answers use business-approved FAQs.
Contact information is saved only with your consent. No payment is collected here.</p>
<noscript>Please enable JavaScript to use the inquiry chat.</noscript></section></main>
<script src="/static/nova-growth/widget.js" data-amicor-growth-token="{escape(row.public_widget_token, quote=True)}"
data-amicor-growth-campaign="{row.id}" defer></script></body></html>'''
