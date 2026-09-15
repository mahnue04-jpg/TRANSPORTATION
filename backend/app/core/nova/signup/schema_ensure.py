"""Create Nova SaaS signup tables without touching Health/Freight schemas."""
from __future__ import annotations

from sqlalchemy import inspect

from app.db.session import engine as default_engine


def ensure_nova_signup_schema(engine=None) -> None:
    bind = engine or default_engine
    inspector = inspect(bind)
    names = set(inspector.get_table_names())
    from app.core.nova.signup.models import (
        NovaCustomerTenant,
        NovaSignupAccount,
        NovaSignupWebhookEvent,
    )

    if "nova_signup_accounts" not in names:
        NovaSignupAccount.__table__.create(bind=bind, checkfirst=True)
    if "nova_customer_tenants" not in names:
        NovaCustomerTenant.__table__.create(bind=bind, checkfirst=True)
    if "nova_signup_webhook_events" not in names:
        NovaSignupWebhookEvent.__table__.create(bind=bind, checkfirst=True)
