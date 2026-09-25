"""Create AMICOR marketplace tables independently from Nova SaaS billing."""
from sqlalchemy import inspect
from app.db.session import engine as default_engine


def ensure_marketplace_schema(engine=None) -> None:
    bind = engine or default_engine
    names = set(inspect(bind).get_table_names())
    from .models import MarketplaceEntitlement, MarketplacePurchase, MarketplaceWebhookEvent
    if "nova_marketplace_purchases" not in names:
        MarketplacePurchase.__table__.create(bind=bind, checkfirst=True)
    if "nova_marketplace_entitlements" not in names:
        MarketplaceEntitlement.__table__.create(bind=bind, checkfirst=True)
    if "nova_marketplace_webhook_events" not in names:
        MarketplaceWebhookEvent.__table__.create(bind=bind, checkfirst=True)
