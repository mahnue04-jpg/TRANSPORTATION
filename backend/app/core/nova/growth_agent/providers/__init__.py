"""Provider adapters. Live transports default off; mock is the only active path."""

from app.core.nova.growth_agent.providers.base import DeliveryResult, ProviderAdapter
from app.core.nova.growth_agent.providers.mock_ai import MockAIAdapter
from app.core.nova.growth_agent.providers.mock_calendar import MockCalendarAdapter
from app.core.nova.growth_agent.providers.mock_email import MockEmailAdapter
from app.core.nova.growth_agent.providers.mock_sms import MockSmsAdapter

__all__ = [
    "DeliveryResult",
    "ProviderAdapter",
    "MockAIAdapter",
    "MockCalendarAdapter",
    "MockEmailAdapter",
    "MockSmsAdapter",
]
