"""Amicor AI Approval Engine — generic workflow infrastructure.

Driver onboarding is the first production workflow. The same case/requirement/
audit pattern is designed to extend to providers, grants, rides, billing, and
compliance without forcing those modules in this release.
"""

from app.modules.approval_engine.statuses import WORKFLOW_STATUSES

__all__ = ["WORKFLOW_STATUSES"]
