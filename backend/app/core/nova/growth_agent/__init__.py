"""AMICOR Nova AI Business Growth Agent — consent-first customer engagement MVP.

Draft / synthetic by default. Live messaging, calendar writes, Stripe charges,
and production DDL require explicit owner approval beyond this package.
"""

from app.core.nova.growth_agent.flags import growth_agent_enabled, live_flags

__all__ = ["growth_agent_enabled", "live_flags"]
