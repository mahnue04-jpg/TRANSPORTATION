"""Create Nova billing tables without touching Health/Freight/Connect schemas."""
from __future__ import annotations

from sqlalchemy import inspect

from app.db.session import engine as default_engine


def ensure_nova_billing_schema(engine=None) -> None:
    bind = engine or default_engine
    inspector = inspect(bind)
    names = set(inspector.get_table_names())
    from app.core.nova.billing.models import NovaBillingWebhookEvent, NovaTenantSubscription

    if "nova_tenant_subscriptions" not in names:
        NovaTenantSubscription.__table__.create(bind=bind, checkfirst=True)
    if "nova_billing_webhook_events" not in names:
        NovaBillingWebhookEvent.__table__.create(bind=bind, checkfirst=True)
