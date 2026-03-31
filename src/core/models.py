"""SQLAlchemy ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("link", name="uq_article_link"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(32), nullable=False, index=True)
    title = Column(Text, nullable=False)
    link = Column(Text, nullable=False, unique=True)
    published_at = Column(DateTime, nullable=True)
    raw_text = Column(Text, nullable=False, default="")
    native_tags = Column(JSONB, nullable=False, default=list)
    estimated_tokens = Column(Integer, nullable=False, default=0)

    status = Column(
        String(32),
        nullable=False,
        default="PENDING",
        index=True,
    )

    summary = Column(Text, nullable=True)
    entities = Column(JSONB, nullable=True)
    embedding = Column(Vector(1536), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Article {self.source}:{self.title[:40]}>"
