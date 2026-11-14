"""Studio campaign handoff; additive and production gated."""
from alembic import op
import sqlalchemy as sa

revision = "20261114_nova_ga_campaigns"
down_revision = "20261112_nova_ga_retention"
branch_labels = None
depends_on = None


def _locked():
    import os
    return any(os.getenv(k, "").lower() in {"prod", "production"}
               for k in ("APP_ENV", "AMICOR_ENVIRONMENT", "ENVIRONMENT"))


def upgrade():
    if _locked():
        return
    from app.core.nova.growth_agent.models import GaCampaign
    GaCampaign.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    if _locked():
        return
    op.drop_table("nova_ga_campaigns")
