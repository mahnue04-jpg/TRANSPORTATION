"""Nova-owned communications hub. Isolated from Health, Delivery, and Freight."""

from app.core.nova.communications.router import router

__all__ = ["router"]
