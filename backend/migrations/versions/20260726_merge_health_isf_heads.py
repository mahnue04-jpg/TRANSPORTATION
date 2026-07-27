"""merge_health_isf_heads

Revision ID: f6e5d4c3b2a1
Revises: c7e4f1a2d8b3, a1b2c3d4e5f6
Create Date: 2026-07-26 21:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union


revision: str = "f6e5d4c3b2a1"
down_revision: Union[str, Sequence[str], None] = ("c7e4f1a2d8b3", "a1b2c3d4e5f6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
