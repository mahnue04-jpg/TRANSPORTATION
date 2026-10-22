from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class NovaLanguagePreference(Base):
    """One screen language per Nova account. This is not a separate product database."""

    __tablename__ = "nova_language_preferences"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    screen_language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
