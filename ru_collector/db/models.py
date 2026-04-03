"""SQLAlchemy models for the RU news collector."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Integer, String, Text, Boolean, Index,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Article(Base):
    """Collected news article from a Russian source."""

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    link = Column(String(2000), nullable=False, unique=True)
    published_at = Column(DateTime(timezone=True), nullable=True, index=True)
    raw_text = Column(Text, nullable=False, default="")
    tags = Column(ARRAY(String), nullable=False, default=list)
    collected_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    synced = Column(Boolean, nullable=False, default=False, index=True)

    __table_args__ = (
        Index("ix_articles_source_published", "source", "published_at"),
        Index("ix_articles_synced_collected", "synced", "collected_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "link": self.link,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "raw_text": self.raw_text,
            "tags": self.tags or [],
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }
