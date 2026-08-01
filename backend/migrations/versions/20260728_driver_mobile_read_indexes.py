"""Add driver-scoped indexes for Driver Mobile read path performance."""
from __future__ import annotations

from alembic import op

revision = "20260728_driver_mobile_read_indexes"
down_revision = "c0d1e2f3a4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_dispatch_assign_driver_state_updated",
        "health_isf_dispatch_assignments",
        ["driver_id", "assignment_state", "updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_dispatch_assign_org_driver_updated",
        "health_isf_dispatch_assignments",
        ["organization_id", "driver_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_rides_org_driver_requested",
        "health_isf_rides",
        ["organization_id", "driver_id", "requested_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_rides_org_driver_requested", table_name="health_isf_rides")
    op.drop_index("idx_dispatch_assign_org_driver_updated", table_name="health_isf_dispatch_assignments")
    op.drop_index("idx_dispatch_assign_driver_state_updated", table_name="health_isf_dispatch_assignments")
